#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker容器流量代理管理器
在2002端口拦截所有请求，直接转发到各服务端口
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
import subprocess
import threading
import requests
from flask import Flask, request, Response
from dataclasses import dataclass
import signal
import sys
import socket
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ContainerConfig:
    """容器配置"""
    service_id: str
    name: str
    port: int
    path: str  # 修改为path，表示URL路径前缀
    startup_command: str
    idle_timeout: int  = 0 # 5分钟无流量停止
    startup_timeout: int = 120
    description: str = ""


@dataclass
class ContainerStatus:
    """容器状态"""
    service_id: str
    name: str
    is_running: bool = False
    is_starting: bool = False
    last_traffic_time: Optional[datetime] = None
    startup_start_time: Optional[datetime] = None
    error_message: str = ""
    request_count: int = 0

    def to_dict(self):
        return {
            'service_id': self.service_id,
            'name': self.name,
            'is_running': self.is_running,
            'is_starting': self.is_starting,
            'last_traffic_time': self.last_traffic_time.isoformat() if self.last_traffic_time else None,
            'error_message': self.error_message,
            'request_count': self.request_count
        }


class DockerProxyManager:
    """Docker容器代理管理器"""
    def __init__(self):
        
        # Authorization配置
        self.required_auth = "MIIEIjANBgkqhkiG9w0BAQEFAAOCBA8AMIIECgKCBAEApg06X2uS+PjAW85nWKMX13/XrZUuWDN/dNOZsAxbDwUelt7UqIack3qKXL1Oa4M5LgPK8QpU0s0KOOsxmScC9XQShnnYomBVpUItGoow+orGAJRpqR3Vi+q1dFm1zOLACk3RTiotntf/WNUC2Pgec+A0rLInDy/i8dIVCK2zTRXalT5K2dzyQiFyilN3u7wZyTaB0ozvGNZ7NeqBX8pA4OuBYSrGYqACum3uYXptIxKMCJDyJvFiulTgmCfBEmPEYYsoNKEKdNOowdMSWmcZiA85BZNl9lvfTf1lQGcpuytkV/MWzCsui7dNdNDIT1E7uAXKGsmloHurR8BSTSZyFe16atsRtsU9Ug1ZPhj3SxrtSYOAfXyYu5/VwyTJE58FZEUaqlmhnNAQKcLc3YqpW208oGC1YWTWP4gcjax8e/k/7VNI/Iwu8WJ3WRB2cAq4Tw0MKEkOs5WiNpujRPZCBAEtP7kxiLZDbyOtVvR+XyoNtq5jZI/7SPNRhVVCXLh+Ci6eoIHsexNhB7D19ckO/4bJY8cACYrR/AutlENZsf38E4DOp9gwNA5R9g2Xq1A8nAoSHt/zHgDYPWBdZJ6D8idiOeQjRtaqzE1SEvATJAd4hHqcOXqXsg1AFE1EXGYo0seuEcpzRbpYjHm+wOdqB64KwlbzN0hhqvsy9iXQiz7qZAZyrQwt39TSN2IJDhRuFmUYNM7rFonI00mL23/L2lEBrK/QeS9TPc9J8uJyexSR2L26VeDKLbWbxeN/g5valcYF/0bOL4lHNqFjUHhBBbWLXXEipZVBu9uaV6TvfJkwcjhWu8deNA6WuHOdPBPq5541ICnzG+a6rVn0iKEWbOByYGLrUaaKkE3DJw0ZLnXdaGXJV/7lXu0mQy1vr6g0+3b1/nR9NCYcz0DWAeeTB5RlIhGGvoYC1oGZOXMZmzQgx7jKDF42nTy6GRWDm/wGRu8asXqY06AEsff9Qa97G75KkVmlbqZ1JBquOSHNTaRgTe/UdgXqFjRJ210ouVq0ETPqClLR6dSkUjFvcEvMKsNg7q4UMSFLFdgflM3vG11j9MvSGLxi2Qk0td1FF7Gt5dH1eB7tf8r/sa3FJzpAW6tKH2cM1QVnYNq5TxvyRr7hmJ3Ik6NDWpmIUNQdZUCzks1cyfkBlC0yjATCZ51OJAhmPzcEOAxWpN89Qu8L2AP7Upw8b4Kcp6OghXwPT+fI518lwa3B6Olk+KEmH+SapoQZ7rW62A9vSMxDLI8pz8N5/AH2VtPyOacyN/JJ4boldFienu1GPK6yOEgjRd4bDcHuDczPzlHvMAXozyI3ihCYFEWtT7uplVK2eiu2w0VgICjB/Vz+m8uaBdd943FaOwIDAQAB"

        # 健康检查主机
        self.health_check_host = '127.0.0.1'

        # 从JSON文件加载容器配置
        self.containers = self._load_service_config()

        # 路径到服务映射
        self.path_to_service = {config.path: service_id for service_id, config in self.containers.items()}

        # 状态跟踪
        self.container_status: Dict[str, ContainerStatus] = {}
        for service_id, config in self.containers.items():
            self.container_status[service_id] = ContainerStatus(service_id=service_id, name=config.name)

        # 启动监控
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_containers, daemon=True)
        self.monitor_thread.start()

        # 初始化时检查已运行的容器并开始计时
        self._initialize_running_containers()

        logger.info(f"代理管理器初始化完成，监听2002端口")
        logger.info(f"从配置文件加载了 {len(self.containers)} 个服务")

    def _load_service_config(self) -> Dict[str, ContainerConfig]:
        """从JSON文件加载服务配置"""
        try:
            # 获取当前脚本所在目录
            current_dir = Path(__file__).parent
            config_file = current_dir / "service.json"

            if not config_file.exists():
                logger.error(f"配置文件不存在: {config_file}")
                return self._get_default_config()

            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            containers = {}
            for service_id, service_config in config_data.items():
                try:
                    # 自动生成启动命令：docker start + 容器名
                    startup_command = f"docker start {service_config['name']}"

                    containers[service_id] = ContainerConfig(
                        service_id=service_config['service_id'],
                        name=service_config['name'],
                        port=service_config['port'],
                        path=service_config['path'],
                        startup_command=startup_command,
                        startup_timeout=service_config.get('startup_timeout', 120),
                        idle_timeout=service_config.get('idle_timeout', 300),
                        description=service_config.get('description', '')
                    )
                    logger.info(f"加载服务配置: {service_id} -> {service_config['name']} (启动命令: {startup_command})")
                except KeyError as e:
                    logger.error(f"服务 {service_id} 配置缺少必要字段: {e}")
                    continue
                except Exception as e:
                    logger.error(f"加载服务 {service_id} 配置时出错: {e}")
                    continue

            if not containers:
                logger.warning("没有成功加载任何服务配置，使用默认配置")
                return self._get_default_config()

            logger.info(f"成功从 {config_file} 加载了 {len(containers)} 个服务配置")
            return containers

        except json.JSONDecodeError as e:
            logger.error(f"JSON配置文件格式错误: {e}")
            return self._get_default_config()
        except Exception as e:
            logger.error(f"加载配置文件时出错: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, ContainerConfig]:
        """获取默认配置（作为备份）"""
        logger.info("使用默认配置")
        return {
            'whisper': ContainerConfig(
                service_id='whisper', name='whisper-asr', port=39000, path='/whisper',
                startup_command='docker start whisper-asr',
                startup_timeout=200, idle_timeout=600, description='中日英 音转文'
            ),
        }

    def reload_config(self) -> bool:
        """重新加载配置文件"""
        try:
            new_containers = self._load_service_config()
            old_services = set(self.containers.keys())
            new_services = set(new_containers.keys())

            # 停止被移除的服务
            removed_services = old_services - new_services
            for service_id in removed_services:
                if service_id in self.container_status:
                    if self.container_status[service_id].is_running:
                        self._stop_container(service_id)
                    del self.container_status[service_id]
                logger.info(f"移除服务: {service_id}")

            # 更新容器配置
            self.containers = new_containers
            self.path_to_service = {config.path: service_id for service_id, config in self.containers.items()}

            # 添加新服务的状态跟踪
            added_services = new_services - old_services
            for service_id in added_services:
                config = self.containers[service_id]
                self.container_status[service_id] = ContainerStatus(service_id=service_id, name=config.name)
                logger.info(f"添加服务: {service_id}")

            logger.info(f"配置重新加载完成，当前管理 {len(self.containers)} 个服务")
            return True

        except Exception as e:
            logger.error(f"重新加载配置失败: {e}")
            return False

    def _initialize_running_containers(self):
        """初始化时检查已运行的容器状态并开始流量计时"""
        current_time = datetime.now()
        running_count = 0

        for service_id, config in self.containers.items():
            status = self.container_status[service_id]
            if self._check_container_running(config.name):
                status.is_running = True
                status.last_traffic_time = current_time
                running_count += 1

        if running_count > 0:
            logger.info(f"初始化完成，发现 {running_count} 个已运行容器")

    def _execute_command(self, command: str) -> tuple[bool, str]:
        """执行系统命令"""
        try:
            result = subprocess.run(command.split(), capture_output=True, text=True, timeout=30)
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def _check_container_running(self, container_name: str) -> bool:
        """检查容器是否运行"""
        try:
            success, output = self._execute_command(f"docker ps --filter name={container_name} --format table")
            return container_name in output and "Up" in output
        except Exception as e:
            logger.error(f"检查容器运行状态失败: {container_name}, 错误: {e}")
            return False

    def _check_container_health(self, config: ContainerConfig) -> bool:
        """检查容器端口是否可联通"""
        try:
            with socket.create_connection((self.health_check_host, config.port), timeout=3):
                return True
        except Exception:
            return False

    def _start_container(self, service_id: str) -> bool:
        """启动容器并等待服务可用"""
        config = self.containers[service_id]
        status = self.container_status[service_id]

        if status.is_running or status.is_starting:
            return True

        logger.info(f"启动容器: {config.name}")
        status.is_starting = True
        status.startup_start_time = datetime.now()
        status.error_message = ""

        try:
            # 第一步：执行启动命令
            success, output = self._execute_command(config.startup_command)
            if not success:
                logger.error(f"启动命令失败: {config.name}, {output}")
                status.is_starting = False
                status.startup_start_time = None
                status.error_message = f"启动失败: {output}"
                return False

            logger.info(f"启动命令执行成功，等待服务就绪: {config.name}")

            # 第二步：等待容器运行并且端口可用
            start_time = datetime.now()
            container_ready = False
            service_ready = False

            while (datetime.now() - start_time).seconds < config.startup_timeout:
                # 检查容器是否运行
                if not container_ready:
                    if self._check_container_running(config.name):
                        container_ready = True
                        logger.info(f"容器已运行: {config.name}")
                    else:
                        time.sleep(1)
                        continue

                # 检查服务端口是否可用
                if container_ready and not service_ready:
                    if self._check_container_health(config):
                        service_ready = True
                        logger.info(f"服务端口已就绪: {config.name}:{config.port}")
                        break
                    else:
                        time.sleep(1)
                        continue

            if not container_ready:
                logger.error(f"容器启动超时: {config.name}")
                status.is_starting = False
                status.startup_start_time = None
                status.error_message = "容器启动超时"
                return False

            if not service_ready:
                logger.error(f"服务端口就绪超时: {config.name}:{config.port}")
                status.is_starting = False
                status.startup_start_time = None
                status.error_message = "服务端口就绪超时"
                return False

            # 启动成功，更新状态
            status.is_running = True
            status.is_starting = False
            status.startup_start_time = None
            status.last_traffic_time = datetime.now()  # 设置初始流量时间
            logger.info(f"容器启动完成: {config.name}")
            return True

        except Exception as e:
            logger.error(f"启动容器异常: {config.name}, 错误: {e}")
            status.is_starting = False
            status.startup_start_time = None
            status.error_message = f"启动异常: {str(e)}"
            return False

    def _stop_container(self, service_id: str) -> bool:
        """停止容器"""
        config = self.containers[service_id]
        status = self.container_status[service_id]

        if not status.is_running:
            return True

        try:
            success, output = self._execute_command(f"docker stop {config.name}")
            if success:
                status.is_running = False
                status.last_traffic_time = None
            return success
        except Exception:
            return False

    def _monitor_containers(self):
        """监控容器状态"""
        while self.monitoring:
            try:
                current_time = datetime.now()
                for service_id, config in self.containers.items():
                    status = self.container_status[service_id]
                    is_actually_running = self._check_container_running(config.name)

                    if status.is_starting:
                        if (status.startup_start_time and
                                current_time - status.startup_start_time > timedelta(seconds=config.startup_timeout)):
                            status.is_starting = False
                            status.startup_start_time = None
                            status.error_message = "启动超时"
                            continue

                        if is_actually_running and self._check_container_health(config):
                            status.is_running = True
                            status.is_starting = False
                            status.startup_start_time = None
                        continue

                    status.is_running = is_actually_running

                    if (status.is_running and
                            status.last_traffic_time and
                            config.idle_timeout > 0 and
                            current_time - status.last_traffic_time > timedelta(seconds=config.idle_timeout)):
                        logger.info(f"无流量超时({config.idle_timeout}秒)，停止容器: {config.name}")
                        self._stop_container(service_id)


            except Exception as e:
                logger.error(f"监控错误: {e}")
            time.sleep(3)

    def check_authorization(self, headers: dict) -> bool:
        """检查authorization头是否有效"""
        auth_header = headers.get('Authorization') or headers.get('authorization')
        if not auth_header:
            return False
        return auth_header == self.required_auth

    def get_service_by_path(self, path: str) -> Optional[str]:
        """根据请求路径匹配对应的Docker服务"""
        for service_path, service_id in self.path_to_service.items():
            if path.startswith(service_path):
                return service_id
        return None

    def record_traffic(self, service_id: str):
        """记录服务流量访问"""
        if service_id in self.container_status:
            status = self.container_status[service_id]
            status.last_traffic_time = datetime.now()
            status.request_count += 1

    def proxy_request(self, path: str, method: str, headers: dict, data: bytes) -> Response:
        """直接转发到服务端口的代理请求"""
        service_id = self.get_service_by_path(path)
        if not service_id:
            return Response(
                json.dumps({'error': 'Service Not Found', 'message': f'未找到路径 {path} 对应的服务'},
                           ensure_ascii=False),
                status=404,
                headers={'Content-Type': 'application/json; charset=utf-8'}
            )

        config = self.containers[service_id]
        max_retries = 5

        # 最多重试5次
        for attempt in range(max_retries):
            try:
                # 移除路径前缀，构建原始API路径
                service_path = path.replace(config.path, '', 1)
                if not service_path.startswith('/'):
                    service_path = '/' + service_path

                target_url = f"http://127.0.0.1:{config.port}{service_path}"
                if request.query_string:
                    target_url += f"?{request.query_string.decode()}"

                # 清理请求头
                clean_headers = {k: v for k, v in headers.items()
                                 if k.lower() not in ['host', 'authorization', 'content-length']}

                # 发送请求到服务端口
                resp = requests.request(
                    method=method,
                    url=target_url,
                    headers=clean_headers,
                    data=data,
                    allow_redirects=False,
                    timeout=120,
                    stream=True
                )

                print(f"resp.status_code: {resp.status_code}")

                # 检查是否需要重试
                if resp.status_code in [502, 503, 504] and attempt < max_retries - 1:
                    print(f"调用错误重试中第{attempt + 1}次错误：状态码{resp.status_code}")
                    wait_time = (attempt + 1) * 2
                    resp.close()
                    time.sleep(wait_time)
                    continue

                # 成功或最后一次尝试，返回结果
                def generate():
                    try:
                        for chunk in resp.iter_content(chunk_size=8192, decode_unicode=False):
                            if chunk:
                                yield chunk
                    finally:
                        resp.close()

                return Response(
                    generate(),
                    status=resp.status_code,
                    headers=[(k, v) for k, v in resp.headers.items()],
                    direct_passthrough=True
                )

            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                # 统一处理连接相关错误
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"连接错误重试中第{attempt + 1}次：{type(e).__name__}: {str(e)}")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"连接最终失败：{type(e).__name__}: {str(e)}")
                    return Response(
                        json.dumps({
                            'error': 'Connection Error',
                            'message': f'服务 {service_id} 连接失败：{str(e)}'
                        }, ensure_ascii=False),
                        status=503,
                        headers={'Content-Type': 'application/json; charset=utf-8'}
                    )

            except requests.exceptions.RequestException as e:
                # 处理其他requests异常
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"请求异常重试中第{attempt + 1}次：{type(e).__name__}: {str(e)}")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"请求最终失败：{type(e).__name__}: {str(e)}")
                    return Response(
                        json.dumps({
                            'error': 'Request Error',
                            'message': f'请求异常：{str(e)}'
                        }, ensure_ascii=False),
                        status=503,
                        headers={'Content-Type': 'application/json; charset=utf-8'}
                    )

            except Exception as e:
                # 处理所有其他异常
                print(f"未知异常：{type(e).__name__}: {str(e)}")
                return Response(
                    json.dumps({
                        'error': 'Proxy Error',
                        'message': f'代理异常：{str(e)}'
                    }, ensure_ascii=False),
                    status=503,
                    headers={'Content-Type': 'application/json; charset=utf-8'}
                )

        return Response(
            json.dumps({
                'error': 'Max retries exceeded',
                'message': f'重试{max_retries}次后仍然失败'
            }, ensure_ascii=False),
            status=503,
            headers={'Content-Type': 'application/json; charset=utf-8'}
        )
    def get_all_status(self) -> dict:
        """获取所有容器详细状态"""
        return {
            'services': {sid: status.to_dict() for sid, status in self.container_status.items()},
            'monitoring_active': self.monitoring,
            'timestamp': datetime.now().isoformat()
        }


# Flask应用
app = Flask(__name__)
manager = DockerProxyManager()

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])
def proxy_all(path):
    """主要的流量拦截和代理处理函数"""
    full_path = f"/{path}"

    # 检查是否是管理接口
    if path.startswith('_admin/'):
        return handle_admin_request(path[7:])

    # 验证authorization头
    if not manager.check_authorization(dict(request.headers)):
        return Response(
            json.dumps({'error': 'Unauthorized', 'message': 'Invalid or missing Authorization header'}),
            status=401,
            headers={'Content-Type': 'application/json'}
        )

    # 根据路径匹配对应的Docker服务
    service_id = manager.get_service_by_path(full_path)

    if service_id:
        # 记录该服务的流量访问
        manager.record_traffic(service_id)

        # 检查服务状态，实现自动启动逻辑
        status = manager.container_status[service_id]
        config = manager.containers[service_id]

        if not status.is_running and not status.is_starting:
            manager._start_container(service_id)

        if not status.is_running:
            # 快速启动检查
            start_time = datetime.now()
            container_started = False

            while (datetime.now() - start_time).seconds < config.startup_timeout:
                if manager._check_container_running(config.name):
                    container_started = True
                    status.is_running = True
                    status.is_starting = False
                    status.startup_start_time = None
                    break
                time.sleep(1)

            if not container_started:
                status.is_starting = False
                status.startup_start_time = None
                status.error_message = "启动超时"
                return Response(
                    json.dumps({'error': 'Service Timeout', 'message': f'服务 {service_id} 启动超时'}),
                    status=503,
                    headers={'Content-Type': 'application/json'}
                )

        return manager.proxy_request(
            full_path,
            request.method,
            dict(request.headers),
            request.get_data()
        )

    # 如果没有匹配的服务，返回404
    return Response(
        json.dumps({'error': 'Not Found', 'message': f'路径 {full_path} 未找到对应服务'}),
        status=404,
        headers={'Content-Type': 'application/json'}
    )


@app.route('/', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])
def proxy_root():
    """处理根路径请求"""
    if not manager.check_authorization(dict(request.headers)):
        return Response(
            json.dumps({'error': 'Unauthorized', 'message': 'Invalid or missing Authorization header'}),
            status=401,
            headers={'Content-Type': 'application/json'}
        )

    return Response(
        json.dumps({'message': 'Docker Proxy Manager', 'version': '1.0'}),
        status=200,
        headers={'Content-Type': 'application/json'}
    )


def handle_admin_request(admin_path):
    """处理管理接口"""
    if admin_path == 'services' and request.method == 'GET':
        services = []
        for service_id, config in manager.containers.items():
            status = manager.container_status[service_id]
            services.append({
                'service_id': service_id,
                'name': config.name,
                'description': config.description,
                'path': config.path,
                'port': config.port,
                'status': {
                    'is_running': status.is_running,
                    'is_starting': status.is_starting,
                    'request_count': status.request_count,
                    'last_traffic_time': status.last_traffic_time.isoformat() if status.last_traffic_time else None
                }
            })
        return {'services': services, 'total_count': len(services)}

    elif admin_path == 'status' and request.method == 'GET':
        return manager.get_all_status()

    elif admin_path == 'reload-config' and request.method == 'POST':
        success = manager.reload_config()
        return {
            'success': success,
            'message': '配置重新加载成功' if success else '配置重新加载失败',
            'service_count': len(manager.containers)
        }


    elif admin_path == 'health' and request.method == 'GET':
        return {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'monitoring_active': manager.monitoring
        }

    else:
        return {'error': 'Not Found'}, 404


def signal_handler(signum, frame):
    manager.monitoring = False
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info("启动Docker代理管理器...")
        logger.info("监听端口: 2002")
        logger.info("管理接口: http://127.0.0.1:2002/_admin/services")
        app.run(host='0.0.0.0', port=2002, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    finally:
        manager.monitoring = False