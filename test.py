#!/usr/bin/env python3
"""
测试Docker代理管理器
"""

import requests
import time


def test_proxy():
    """测试代理功能"""
    print("=== 测试Docker代理管理器 ===\n")

    # 1. 查看管理接口
    print("1. 查看服务状态:")
    try:
        resp = requests.get("http://127.0.0.1:2002/_admin/services")
        if resp.status_code == 200:
            services = resp.json()['services']
            for svc in services:
                print(f"  - {svc['service_id']}: {svc['description']}")
                print(f"    路径: {svc['nginx_path']}, 请求数: {svc['status']['request_count']}")
                print(f"    状态: {'运行中' if svc['status']['is_running'] else '未运行'}")
        else:
            print(f"  获取失败: {resp.status_code}")
    except Exception as e:
        print(f"  连接失败: {e}")
    print()

    # 2. 测试流量拦截
    print("2. 测试流量拦截 (访问 /pdocr/):")
    try:
        HEADERS = {
            "Authorization": "MIIEIjANBgkqhkiG9w0BAQEFAAOCBA8AMIIECgKCBAEApg06X2uS+PjAW85nWKMX13/XrZUuWDN/dNOZsAxbDwUelt7UqIack3qKXL1Oa4M5LgPK8QpU0s0KOOsxmScC9XQShnnYomBVpUItGoow+orGAJRpqR3Vi+q1dFm1zOLACk3RTiotntf/WNUC2Pgec+A0rLInDy/i8dIVCK2zTRXalT5K2dzyQiFyilN3u7wZyTaB0ozvGNZ7NeqBX8pA4OuBYSrGYqACum3uYXptIxKMCJDyJvFiulTgmCfBEmPEYYsoNKEKdNOowdMSWmcZiA85BZNl9lvfTf1lQGcpuytkV/MWzCsui7dNdNDIT1E7uAXKGsmloHurR8BSTSZyFe16atsRtsU9Ug1ZPhj3SxrtSYOAfXyYu5/VwyTJE58FZEUaqlmhnNAQKcLc3YqpW208oGC1YWTWP4gcjax8e/k/7VNI/Iwu8WJ3WRB2cAq4Tw0MKEkOs5WiNpujRPZCBAEtP7kxiLZDbyOtVvR+XyoNtq5jZI/7SPNRhVVCXLh+Ci6eoIHsexNhB7D19ckO/4bJY8cACYrR/AutlENZsf38E4DOp9gwNA5R9g2Xq1A8nAoSHt/zHgDYPWBdZJ6D8idiOeQjRtaqzE1SEvATJAd4hHqcOXqXsg1AFE1EXGYo0seuEcpzRbpYjHm+wOdqB64KwlbzN0hhqvsy9iXQiz7qZAZyrQwt39TSN2IJDhRuFmUYNM7rFonI00mL23/L2lEBrK/QeS9TPc9J8uJyexSR2L26VeDKLbWbxeN/g5valcYF/0bOL4lHNqFjUHhBBbWLXXEipZVBu9uaV6TvfJkwcjhWu8deNA6WuHOdPBPq5541ICnzG+a6rVn0iKEWbOByYGLrUaaKkE3DJw0ZLnXdaGXJV/7lXu0mQy1vr6g0+3b1/nR9NCYcz0DWAeeTB5RlIhGGvoYC1oGZOXMZmzQgx7jKDF42nTy6GRWDm/wGRu8asXqY06AEsff9Qa97G75KkVmlbqZ1JBquOSHNTaRgTe/UdgXqFjRJ210ouVq0ETPqClLR6dSkUjFvcEvMKsNg7q4UMSFLFdgflM3vG11j9MvSGLxi2Qk0td1FF7Gt5dH1eB7tf8r/sa3FJzpAW6tKH2cM1QVnYNq5TxvyRr7hmJ3Ik6NDWpmIUNQdZUCzks1cyfkBlC0yjATCZ51OJAhmPzcEOAxWpN89Qu8L2AP7Upw8b4Kcp6OghXwPT+fI518lwa3B6Olk+KEmH+SapoQZ7rW62A9vSMxDLI8pz8N5/AH2VtPyOacyN/JJ4boldFienu1GPK6yOEgjRd4bDcHuDczPzlHvMAXozyI3ihCYFEWtT7uplVK2eiu2w0VgICjB/Vz+m8uaBdd943FaOwIDAQAB"
        }
        # 模拟访问pdocr服务
        resp = requests.get("http://127.0.0.1:2002/pdocr/health", headers= HEADERS,timeout=10)
        print(f"  响应状态: {resp.status_code}")
        if resp.status_code == 202:
            print("  服务启动中...")
        elif resp.status_code == 200:
            print("  服务正常响应")
        else:
            print(f"  响应内容: {resp.text[:200]}")
    except Exception as e:
        print(f"  请求失败: {e}")
    print()

    # 3. 再次查看状态
    print("3. 查看流量记录:")
    try:
        resp = requests.get("http://127.0.0.1:2002/_admin/status")
        if resp.status_code == 200:
            data = resp.json()
            for sid, status in data['services'].items():
                if status['request_count'] > 0:
                    print(f"  {sid}: {status['request_count']} 次请求")
                    if status['last_traffic_time']:
                        print(f"    最后流量: {status['last_traffic_time']}")
    except Exception as e:
        print(f"  获取状态失败: {e}")
    print()

    print("测试完成！")
    print("\n使用说明:")
    print("1. 启动代理: python3 docker_manager.py")
    print("2. 修改nginx监听端口为2003")
    print("3. 所有请求发送到2002端口")
    print("4. 管理接口: http://127.0.0.1:2002/_admin/services")




def show_curl_examples():
    """显示curl使用示例"""
    print("\n=== curl使用示例 ===")
    print("# 访问服务 (会自动记录流量)")
    print("curl http://127.0.0.1:2002/pdocr/health")
    print("curl http://127.0.0.1:2002/mineru/health")
    print("curl http://127.0.0.1:2002/voicevox/version")
    print()
    print("# 查看管理信息")
    print("curl http://127.0.0.1:2002/_admin/services")
    print("curl http://127.0.0.1:2002/_admin/status")
    print("curl http://127.0.0.1:2002/_admin/health")
    print()
    print("# 手动停止服务")
    print("curl -X POST http://127.0.0.1:2002/_admin/services/pdocr/stop")


if __name__ == "__main__":
    test_proxy()
    show_curl_examples()