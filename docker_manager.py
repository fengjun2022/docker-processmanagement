#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker容器流量代理管理器
在2002端口拦截所有请求，监测流量后转发到nginx(2003)
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

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ContainerConfig:
    """容器配置"""
    service_id: str
    name: str
    port: int
    nginx_path: str
    startup_command: str
    startup_timeout: int = 120
    idle_timeout: int = 300  # 5分钟无流量停止
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
        # Authorization配置 - 请填入你的authorization值
        self.required_auth = "MIIEIjANBgkqhkiG9w0BAQEFAAOCBA8AMIIECgKCBAEApg06X2uS+PjAW85nWKMX13/XrZUuWDN/dNOZsAxbDwUelt7UqIack3qKXL1Oa4M5LgPK8QpU0s0KOOsxmScC9XQShnnYomBVpUItGoow+orGAJRpqR3Vi+q1dFm1zOLACk3RTiotntf/WNUC2Pgec+A0rLInDy/i8dIVCK2zTRXalT5K2dzyQiFyilN3u7wZyTaB0ozvGNZ7NeqBX8pA4OuBYSrGYqACum3uYXptIxKMCJDyJvFiulTgmCfBEmPEYYsoNKEKdNOowdMSWmcZiA85BZNl9lvfTf1lQGcpuytkV/MWzCsui7dNdNDIT1E7uAXKGsmloHurR8BSTSZyFe16atsRtsU9Ug1ZPhj3SxrtSYOAfXyYu5/VwyTJE58FZEUaqlmhnNAQKcLc3YqpW208oGC1YWTWP4gcjax8e/k/7VNI/Iwu8WJ3WRB2cAq4Tw0MKEkOs5WiNpujRPZCBAEtP7kxiLZDbyOtVvR+XyoNtq5jZI/7SPNRhVVCXLh+Ci6eoIHsexNhB7D19ckO/4bJY8cACYrR/AutlENZsf38E4DOp9gwNA5R9g2Xq1A8nAoSHt/zHgDYPWBdZJ6D8idiOeQjRtaqzE1SEvATJAd4hHqcOXqXsg1AFE1EXGYo0seuEcpzRbpYjHm+wOdqB64KwlbzN0hhqvsy9iXQiz7qZAZyrQwt39TSN2IJDhRuFmUYNM7rFonI00mL23/L2lEBrK/QeS9TPc9J8uJyexSR2L26VeDKLbWbxeN/g5valcYF/0bOL4lHNqFjUHhBBbWLXXEipZVBu9uaV6TvfJkwcjhWu8deNA6WuHOdPBPq5541ICnzG+a6rVn0iKEWbOByYGLrUaaKkE3DJw0ZLnXdaGXJV/7lXu0mQy1vr6g0+3b1/nR9NCYcz0DWAeeTB5RlIhGGvoYC1oGZOXMZmzQgx7jKDF42nTy6GRWDm/wGRu8asXqY06AEsff9Qa97G75KkVmlbqZ1JBquOSHNTaRgTe/UdgXqFjRJ210ouVq0ETPqClLR6dSkUjFvcEvMKsNg7q4UMSFLFdgflM3vG11j9MvSGLxi2Qk0td1FF7Gt5dH1eB7tf8r/sa3FJzpAW6tKH2cM1QVnYNq5TxvyRr7hmJ3Ik6NDWpmIUNQdZUCzks1cyfkBlC0yjATCZ51OJAhmPzcEOAxWpN89Qu8L2AP7Upw8b4Kcp6OghXwPT+fI518lwa3B6Olk+KEmH+SapoQZ7rW62A9vSMxDLI8pz8N5/AH2VtPyOacyN/JJ4boldFienu1GPK6yOEgjRd4bDcHuDczPzlHvMAXozyI3ihCYFEWtT7uplVK2eiu2w0VgICjB/Vz+m8uaBdd943FaOwIDAQAB"
        self._check_container_health = 'http://127.0.0.1'
        # 配置容器
        self.containers = {
            'pdocr': ContainerConfig(
                service_id='pdocr', name='paddle-ocr-api', port=8000, nginx_path='/pdocr/',
                startup_command='docker start paddle-ocr-api',
                startup_timeout=180,
                description='PaddleOCR文字识别服务'
            ),
            'mineru': ContainerConfig(
                service_id='mineru', name='mineru-api', port=18000, nginx_path='/mineru/',
                startup_command='docker start mineru-api',
                startup_timeout=180, description='MinerU文档解析服务'
            ),

            'voicevox': ContainerConfig(
                service_id='voicevox', name='voicevox-voicevox-1', port=50021, nginx_path='/voicevox/',
                startup_command='docker start voicevox-voicevox-1',
                startup_timeout=150, description='VOICEVOX语音合成服务'
            ),
            'qwen-embedding': ContainerConfig(
                service_id='qwen-embedding', name='qwen-embedding-4b', port=30981, nginx_path='/qwen-embedding-4b/',
                startup_command='docker start qwen-embedding-4b',
                startup_timeout=200, idle_timeout=600, description='Qwen嵌入模型服务'
            ),

            'coquai': ContainerConfig(
                service_id='coquai', name='coqui-tts-gpu', port=5003, nginx_path='/coquai/',
                startup_command='docker start coqui-tts-gpu',
                startup_timeout=200, idle_timeout=600, description='英文中文tts服务'
            )

        }

        # 路径到服务映射
        self.path_to_service = {config.nginx_path.rstrip('/'): service_id
                                for service_id, config in self.containers.items()}

        # 状态跟踪
        self.container_status: Dict[str, ContainerStatus] = {}
        for service_id, config in self.containers.items():
            self.container_status[service_id] = ContainerStatus(service_id=service_id, name=config.name)

        # Nginx后端地址
        self.nginx_backend = "http://127.0.0.1:2003"

        # 启动监控
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_containers, daemon=True)
        self.monitor_thread.start()

        # 初始化时检查已运行的容器并开始计时
        self._initialize_running_containers()

        logger.info(f"代理管理器初始化完成，监听2002端口，转发到{self.nginx_backend}")
        logger.info(f"管理服务: {list(self.containers.keys())}")

    def _initialize_running_containers(self):
        """
        初始化时检查已运行的容器状态并开始流量计时

        作用:
        1. 检查所有配置的容器当前运行状态
        2. 对已运行的容器设置初始流量时间
        3. 避免已运行容器因为没有访问记录而被立即停止
        """
        current_time = datetime.now()
        running_count = 0

        for service_id, config in self.containers.items():
            status = self.container_status[service_id]

            # 检查容器是否已经在运行
            if self._check_container_running(config.name):
                status.is_running = True
                status.last_traffic_time = current_time  # 设置初始流量时间
                running_count += 1
                logger.info(f"发现已运行容器: {config.name}, 开始流量计时")
            else:
                status.is_running = False

        if running_count > 0:
            logger.info(f"初始化完成，发现 {running_count} 个已运行容器并开始计时")
        else:
            logger.info("初始化完成，没有发现运行中的容器")

    def _execute_command(self, command: str) -> tuple[bool, str]:
        """执行系统命令"""
        try:
            result = subprocess.run(command.split(), capture_output=True, text=True, timeout=30)
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def _check_container_running(self, container_name: str) -> bool:
        """检查容器是否运行"""
        success, output = self._execute_command(f"docker ps --filter name={container_name} --format table")
        return container_name in output and "Up" in output

    def _check_container_health(self, config: ContainerConfig) -> bool:
        """检查容器端口是否可联通"""
        try:
            port = config.port  # 例如 5002
            with socket.create_connection((self._check_container_health, port), timeout=3):
                return True
        except Exception:
            return False

    def _start_container(self, service_id: str) -> bool:
        """启动容器"""
        config = self.containers[service_id]
        status = self.container_status[service_id]

        if status.is_running or status.is_starting:
            return True

        logger.info(f"启动容器: {config.name}")
        status.is_starting = True
        status.startup_start_time = datetime.now()
        status.error_message = ""

        success, output = self._execute_command(config.startup_command)
        if not success:
            logger.error(f"启动失败: {config.name}, {output}")
            status.is_starting = False
            status.startup_start_time = None
            status.error_message = f"启动失败: {output}"
            return False

        return True

    def _stop_container(self, service_id: str) -> bool:
        """停止容器"""
        config = self.containers[service_id]
        status = self.container_status[service_id]

        if not status.is_running:
            return True

        logger.info(f"停止容器: {config.name}")
        success, output = self._execute_command(f"docker stop {config.name}")

        if success:
            status.is_running = False
            status.last_traffic_time = None
            logger.info(f"容器已停止: {config.name}")

        return success

    def _monitor_containers(self):
        """监控容器状态"""
        while self.monitoring:
            try:
                current_time = datetime.now()

                for service_id, config in self.containers.items():
                    status = self.container_status[service_id]
                    is_actually_running = self._check_container_running(config.name)

                    # 处理启动中状态
                    if status.is_starting:
                        if (status.startup_start_time and
                                current_time - status.startup_start_time > timedelta(seconds=config.startup_timeout)):
                            logger.warning(f"启动超时: {config.name}")
                            status.is_starting = False
                            status.startup_start_time = None
                            status.error_message = "启动超时"
                            continue

                        if is_actually_running and self._check_container_health(config):
                            logger.info(f"启动成功: {config.name}")
                            status.is_running = True
                            status.is_starting = False
                            status.startup_start_time = None
                        continue

                    # 更新运行状态
                    status.is_running = is_actually_running

                    # 检查流量空闲超时
                    if (status.is_running and status.last_traffic_time and
                            current_time - status.last_traffic_time > timedelta(seconds=config.idle_timeout)):
                        logger.info(f"无流量超时，停止容器: {config.name}")
                        self._stop_container(service_id)

            except Exception as e:
                logger.error(f"监控错误: {e}")

            time.sleep(3)

    def check_authorization(self, headers: dict) -> bool:
        """
        检查authorization头是否有效

        检查逻辑:
        1. 从请求头中提取Authorization字段
        2. 与预设的required_auth进行比较
        3. 返回验证结果
        """
        auth_header = headers.get('Authorization') or headers.get('authorization')
        if not auth_header:
            logger.debug("请求缺少Authorization头")
            return False

        is_valid = auth_header == self.required_auth
        if not is_valid:
            logger.debug(f"Authorization验证失败: {auth_header[:20]}...")

        return is_valid

    def get_service_by_path(self, path: str) -> Optional[str]:
        """
        根据请求路径匹配对应的Docker服务

        匹配逻辑:
        - /pdocr/ -> pdocr服务
        - /mineru/ -> mineru服务
        - /file_mineru/ -> mineru-file服务
        - /voicevox/ -> voicevox服务
        - /qwen-embedding-4b/ -> qwen-embedding服务

        返回匹配的service_id，用于流量记录和容器管理
        """
        # 精确匹配路径前缀
        for nginx_path, service_id in self.path_to_service.items():
            if path.startswith(nginx_path):
                return service_id
        return None

    def record_traffic(self, service_id: str):
        """
        记录服务流量访问

        作用:
        1. 更新服务的最后流量时间（用于空闲超时判断）
        2. 增加请求计数器
        3. 防止服务因5分钟无流量而被自动停止
        """
        if service_id in self.container_status:
            status = self.container_status[service_id]
            status.last_traffic_time = datetime.now()
            status.request_count += 1

    def precheck_service(self, service_id: str) -> dict:
        """预检服务"""
        if service_id not in self.containers:
            return {'success': False, 'status': 'error', 'message': f'未找到服务: {service_id}'}

        config = self.containers[service_id]
        status = self.container_status[service_id]

        if status.is_running:
            return {'success': True, 'status': 'running'}
        elif status.is_starting:
            return {'success': True, 'status': 'starting'}
        else:
            self._start_container(service_id)
            return {'success': True, 'status': 'starting'}

    def proxy_request(self, path: str, method: str, headers: dict, data: bytes) -> Response:
        """
        代理请求到nginx后端

        调用逻辑:
        1. 构建转发到nginx(2003端口)的完整URL
        2. 过滤掉authorization头（因为已在Python层验证）
        3. 转发请求到nginx
        4. 将nginx响应原样返回给客户端
        """
        try:
            # 构建目标URL - 转发到nginx的2003端口
            target_url = f"{self.nginx_backend}{path}"
            if request.query_string:
                target_url += f"?{request.query_string.decode()}"

            # 准备转发的请求头，排除authorization头
            forward_headers = {}
            for k, v in headers.items():
                # 过滤掉会冲突的头和authorization头
                if k.lower() not in ['host', 'content-length', 'authorization']:
                    forward_headers[k] = v

            # 转发请求到nginx后端（不包含authorization头）
            resp = requests.request(
                method=method,
                url=target_url,
                headers=forward_headers,
                data=data,
                stream=True,
                timeout=60
            )

            # 构建响应 - 将nginx的响应原样返回
            response = Response(
                resp.content,
                status=resp.status_code,
                headers=dict(resp.headers)
            )

            logger.debug(f"代理请求成功: {method} {path} -> {resp.status_code}")
            return response

        except Exception as e:
            logger.error(f"代理请求失败: {method} {path}, 错误: {e}")
            return Response(
                json.dumps({'error': 'Proxy Error', 'message': str(e)}),
                status=503,
                headers={'Content-Type': 'application/json'}
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
    """
    主要的流量拦截和代理处理函数

    调用逻辑:
    1. 拦截所有发到2002端口的请求
    2. 检查authorization头，验证失败返回401
    3. 检查是否为管理接口(_admin/)，如果是则内部处理
    4. 根据请求路径匹配对应的Docker服务
    5. 记录服务流量，更新最后访问时间
    6. 检查服务状态，如果未运行则自动启动容器
    7. 如果服务正在启动中，返回202状态提示等待
    8. 将请求转发给nginx(2003端口)，不包含authorization头
    9. 将nginx响应原样返回给客户端
    """
    full_path = f"/{path}"

    # 检查是否是管理接口 - 内部处理，不转发
    if path.startswith('_admin/'):
        return handle_admin_request(path[7:])  # 去掉 '_admin/' 前缀

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
        logger.debug(f"流量记录: {service_id} - {full_path}")

        # 检查服务状态，实现自动启动逻辑
        status = manager.container_status[service_id]
        config = manager.containers[service_id]

        if not status.is_running and not status.is_starting:
            logger.info(f"检测到请求，自动启动服务: {service_id}")
            manager._start_container(service_id)

        # 如果服务未运行或正在启动，等待启动完成
        if not status.is_running:
            logger.info(f"等待服务启动完成: {service_id}")

            # 等待容器启动，最多等待startup_timeout秒
            start_time = datetime.now()
            while (datetime.now() - start_time).seconds < config.startup_timeout:
                # 检查容器是否已启动并健康
                if (manager._check_container_running(config.name) and
                        manager._check_container_health(config)):
                    status.is_running = True
                    status.is_starting = False
                    status.startup_start_time = None
                    logger.info(f"服务启动完成: {service_id}")
                    break

                # 短暂等待后重试
                time.sleep(1)
            else:
                # 启动超时
                logger.error(f"服务启动超时: {service_id}")
                status.is_starting = False
                status.startup_start_time = None
                status.error_message = "启动超时"
                return Response(
                    json.dumps({
                        'error': 'Service Timeout',
                        'message': f'服务 {service_id} 启动超时',
                        'timeout': config.startup_timeout
                    }),
                    status=503,
                    headers={'Content-Type': 'application/json'}
                )

    # 代理请求到nginx(2003端口)，不包含authorization头
    return manager.proxy_request(
        full_path,
        request.method,
        dict(request.headers),
        request.get_data()
    )


@app.route('/', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])
def proxy_root():
    """
    处理根路径请求

    调用逻辑:
    1. 验证authorization头
    2. 转发到nginx，nginx不需要再验证authorization
    """
    # 验证authorization头
    if not manager.check_authorization(dict(request.headers)):
        return Response(
            json.dumps({'error': 'Unauthorized', 'message': 'Invalid or missing Authorization header'}),
            status=401,
            headers={'Content-Type': 'application/json'}
        )

    return manager.proxy_request(
        '/',
        request.method,
        dict(request.headers),
        request.get_data()
    )


def handle_admin_request(admin_path):
    """处理管理接口"""
    if admin_path == 'services' and request.method == 'GET':
        # 获取服务列表
        services = []
        for service_id, config in manager.containers.items():
            status = manager.container_status[service_id]
            services.append({
                'service_id': service_id,
                'name': config.name,
                'description': config.description,
                'nginx_path': config.nginx_path,
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
        # 获取状态
        return {
            'services': {sid: status.to_dict() for sid, status in manager.container_status.items()},
            'monitoring_active': manager.monitoring,
            'nginx_backend': manager.nginx_backend,
            'timestamp': datetime.now().isoformat()
        }

    elif admin_path.startswith('services/') and admin_path.endswith('/stop') and request.method == 'POST':
        # 停止服务
        service_id = admin_path.split('/')[1]
        if service_id in manager.containers:
            success = manager._stop_container(service_id)
            return {'success': success, 'message': '已停止' if success else '停止失败'}
        else:
            return {'success': False, 'message': f'未找到服务: {service_id}'}, 404

    elif admin_path == 'health' and request.method == 'GET':
        # 健康检查
        return {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'monitoring_active': manager.monitoring,
            'nginx_backend': manager.nginx_backend
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
        logger.info("转发目标: http://127.0.0.1:2003")
        logger.info("管理接口: http://127.0.0.1:2002/_admin/services")

        app.run(host='0.0.0.0', port=2002, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    finally:
        manager.monitoring = False