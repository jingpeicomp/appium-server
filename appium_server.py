# coding=utf-8
import datetime
import getopt
import logging
import os
import shlex
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler

import flask
from flask import Flask, request
from flask_restful import Api, Resource
from redislog.tdummy.handlers import LogstashRedisHandler

app = Flask(__name__)
api = Api(app)

logger = app.logger


class AdbConnection(object):
    """
    Adb connection管理
    """

    device_ip_name = {}

    @staticmethod
    def create_adb_conn(device_ip, device_port='5555'):
        """
        创建adb连接
        :return:
        """
        logger.info('create_adb_conn is called {0} {1}'.format(device_ip, device_port))
        adb_connect_command = 'adb connect {0}:{1}'.format(device_ip, device_port)
        is_success, command_result = execute_command(adb_connect_command)
        command_result = ''.join(command_result).strip(' \n')
        return is_success and (
            command_result.startswith('already connected to') or command_result.startswith('connected to'))

    @staticmethod
    def get_all_conn(ip=None):
        """
        获取adb连接
        :param ip:
        :return:
        """
        list_device_cmd = 'adb devices -l'
        is_success, command_result = execute_command(list_device_cmd)
        if not is_success:
            return {}

        command_device_list = filter(lambda _line: _line and not _line.startswith('List of devices'),
                                     map(lambda _line: _line.strip('\n '), command_result))
        device_dict = {}
        for command_device_str in command_device_list:
            device_ip, device_id = filter(lambda item: item, command_device_str.split('  '))
            device_dict[device_ip] = {'ip': device_ip.strip(' '), 'id': device_id.strip(' ')}
            if ip and ip == device_ip:
                return device_dict[device_ip]

        return device_dict


class AppiumServer(Resource):
    """
    Appium Server管理
    """

    server_cache = {}

    def post(self):
        """
        创建一个Appium Server
        :return:
        """
        post_data = request.get_json()
        if 'deviceIp' not in post_data:
            abort(400, message="Device ip cannot be null")

        device_ip = post_data.get('deviceIp')
        device_port = post_data.get('devicePort') or '5555'
        device_udid = '{0}:{1}'.format(device_ip, device_port)

        is_success = AdbConnection.create_adb_conn(device_ip, device_port)
        if not is_success:
            logger.error('Fail to create adb connection {0}'.format(device_udid))
            abort(500, message="Cannot connect the device {0} by adb, please check the phone".format(device_udid))

        if self.server_cache.get(device_udid):
            return self.server_cache.get(device_udid)

        server_port = self._get_server_port()
        if not server_port:
            abort(500, message="Cannot get available appium server port".format(device_udid))
        server_bport = server_port + 1

        server_command = 'node /root/node-v4.6.0-linux-x64/lib/node_modules/appium -p {0} -bp {1} -U {2}'.format(
            server_port, server_bport, device_udid)
        is_success, _ = execute_command(server_command, background=True)
        if not is_success:
            logger.error('Fail to start appium server'.format(server_command))
            abort(500, message="Cannot start appium server {0}".format(device_udid))

        self.server_cache[device_udid] = {'server_port': server_port, 'server_bport': server_port,
                                          'server_ip': ip_address}

        return self.server_cache[device_udid]

    def get(self):
        """
        查询正在运行的server
        :return:
        """
        return self.server_cache

    def _get_server_port(self):
        """
        获取可用的APPIUM server端口
        :return:
        """
        used_ports = map(lambda item: item['server_port'], self.server_cache.itervalues())
        for cur_port in xrange(25000, 26000, 2):
            if cur_port not in used_ports:
                return cur_port

        logger.error('Cannot get available appium server port')
        return 0


@app.route('/adb/connection', methods=['post'])
def adb_connect():
    request_body = request.json
    device_ip = request_body.get('deviceIp')
    if not device_ip:
        abort(400)


def execute_command(cmd_string, cwd=None, timeout=180, shell=True, background=False):
    """
    执行一个SHELL命令
        封装了subprocess的Popen方法, 支持超时判断，支持读取stdout和stderr
           参数:
        cwd: 运行命令时更改路径，如果被设定，子进程会直接先更改当前路径到cwd
        timeout: 超时时间，秒，支持小数，精度0.1秒
        shell: 是否通过shell运行
        background: 是否需要后台执行
    Returns: return_code
    """
    if background:
        cmd_string += ' &'
    if shell:
        cmd_string_list = cmd_string
    else:
        cmd_string_list = shlex.split(cmd_string)

    logger.info('Begin execute command {0}'.format(cmd_string_list))
    if timeout:
        end_time = datetime.datetime.now() + datetime.timedelta(seconds=timeout)

    # 没有指定标准输出和错误输出的管道，因此会打印到屏幕上；
    sub = subprocess.Popen(cmd_string_list, cwd=cwd, stdin=subprocess.PIPE, shell=shell, bufsize=4096,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # subprocess.poll()方法：检查子进程是否结束了，如果结束了，设定并返回码，放在subprocess.returncode变量中
    while sub.poll() is None:
        time.sleep(0.1)
        if timeout:
            if end_time <= datetime.datetime.now():
                logger.error('The command is timeout {0}'.format(cmd_string))
                return False, 'Timeout：%s' % cmd_string

    # 如果是后台执行需要检查是否存在进程
    if background:
        count = 0
        grep_cmd = ' ps -ef | grep "{0}" | grep -v grep'.format(cmd_string)
        while count < 10:
            time.sleep(0.1)
            grep_sub = subprocess.Popen(grep_cmd, cwd=cwd, stdin=subprocess.PIPE, shell=shell, bufsize=4096,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = grep_sub.readlines()
            if result:
                logger.info('Finish execute command with result {0}'.format(result))
                return True, result

        logger.error('Fail execute command')
        return False, ''

    result = sub.stdout.readlines()
    logger.info('Finish execute command with result {0}'.format(result))
    return True, result


def abort(code, message=None):
    """
    输出response body
    :param code:
    :param message:
    :return:
    """
    if message:
        return flask.abort(code, {'detail': message})
    else:
        return flask.abort(code)


def config_log(production_env=False):
    """
    配置日志文件
    :param production_env 是否是生产环境,如果是生产环境那么需要将日志写入到ELK中
    :return:
    """
    if not production_env:
        base_dir = os.path.dirname(__file__)
        handler = RotatingFileHandler(os.path.join(base_dir, 'logs/app.log'), maxBytes=10000000, backupCount=1)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    else:
        handler = LogstashRedisHandler(level=logging.INFO, is_interface_handler=False, key='LOGSTASH_APP_LOG',
                                       host='192.168.65.224', app_module='appium_server')
        logger.addHandler(handler)


def parse_system_argv():
    """
    解析命令行参数
    :return:
    """
    opts, _ = getopt.getopt(sys.argv[1:], '', ["production="])
    production = False
    for opt, value in opts:
        if opt == '--production':
            production = value.lower() == 'true'

    return {'production': production}


def get_ip():
    """
    获取本机IP地址
    :return:
    """
    import socket
    host_name = socket.getfqdn(socket.gethostname())
    return socket.gethostbyname(host_name)


ip_address = get_ip()

api.add_resource(AppiumServer, '/appium/servers')

if __name__ == '__main__':
    env_path = os.getenv('PATH')
    os.putenv('PATH', env_path + ':' + '/usr/local/bin')

    start_opts = parse_system_argv()
    config_log(start_opts['production'])
    print start_opts
    app.run(host='0.0.0.0', debug=False)
