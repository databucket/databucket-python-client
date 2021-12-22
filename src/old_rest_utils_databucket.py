# Created for databucket2.py library
# Library rest_utils makes some ugly errors with Databucket :[
import json
import logging
import re
import socket
import traceback
from datetime import datetime
from http.client import responses

import requests
from requests import Response, Session

log = logging.getLogger()


class DatabucketRestClient:
    # running_inside_tn_network = True
    __enable_logging = False
    __log_headers = False
    __log_console = False
    __headers = None
    __proxy = None
    request = None
    response = None
    __last_request_time = datetime.now()

    def __init__(self, headers=None):
        if headers is None:
            headers = {}
        self.__headers = headers

    def set_enabled_log(self, enabled: bool):
        self.__enable_logging = enabled

    def set_enabled_log_headers(self, enabled: bool):
        self.__log_headers = enabled

    def set_enabled_log_console(self, enabled: bool):
        self.__log_console = enabled

    def set_headers(self, headers):
        self.__headers = headers

    def set_proxy(self, proxy):
        self.__proxy = proxy

    def __send_request(self, method: str, url: str, data: str = None, verify_response_status: bool = True, params: dict = None) -> Response:
        self.request = None
        self.response = None

        self.request = requests.Request(method, url, headers=self.__headers, data=data, params=params).prepare()

        session = Session()
        # if self.running_inside_tn_network and proxy:  # communication via proxy is required between machine inside TN network (GoCD agent) and Databucket REST service
        if self.__proxy:
            session.proxies = {'http': self.__proxy, 'https': self.__proxy}
        session.verify = False  # SSL Verification

        if 'OPL0000PC00361S' in socket.gethostname() and 'databucket' in url:  # Running from Pawel Kazmierski PC
            session.proxies = {'http': '126.179.0.206:9090', 'https': '126.179.0.206:9090'}
        session.verify = False  # SSL Verification

        if 'MatrixxPaymentCompanion' in url:
            assertion_prefix = 'MPC: '
        elif 'databucket' in url:
            assertion_prefix = 'Databucket: '
        else:
            assertion_prefix = 'MXX: '

        try:
            self.response = session.send(self.request, timeout=120)

        # http://docs.python-requests.org/en/master/_modules/requests/exceptions/
        except requests.exceptions.InvalidProxyURL:
            raise AssertionError(f'{assertion_prefix}InvaliProxydURL: {session.proxies["https"]} used when connecting to {url}.')
        except requests.exceptions.InvalidURL:
            raise AssertionError(f'{assertion_prefix}InvalidURL exception for {url}.')
        except requests.exceptions.ConnectTimeout:
            raise AssertionError(f'{assertion_prefix}ConnectTimeout ({120} s) exception for {url}.')
        except requests.exceptions.ReadTimeout:
            raise AssertionError(f'{assertion_prefix}Response ReadTimeout ({120} s) exception for {url}.')
        except requests.exceptions.ConnectionError as ex:
            raise AssertionError(f'{assertion_prefix}Failed to connect to {url}.\n{ex} ')

        # self.log_any_request_response()
        if self.__enable_logging or self.__log_console:
            try:
                self.log_any_request_response()
            except Exception:
                pass

        if verify_response_status:
            # http://docs.python-requests.org/en/master/api/
            if not self.response.ok:
                raise AssertionError(f'{assertion_prefix}Unexpected response status: {self.response.status_code} ({responses[self.response.status_code]}).\nRequested URL: {url}.')

        self.__last_request_time = datetime.now()

        return self.response

    def get(self, url: str, verify_response_status: bool = True) -> Response:
        return self.__send_request('GET', url=url, data=None, verify_response_status=verify_response_status)

    def post(self, url: str, data: str = None, verify_response_status: bool = True) -> Response:
        return self.__send_request('POST', url=url, data=data, verify_response_status=verify_response_status)

    def put(self, url: str, data: str = None, verify_response_status: bool = True) -> Response:
        return self.__send_request('PUT', url=url, data=data, verify_response_status=verify_response_status)

    def delete(self, url: str, data: str = None, verify_response_status: bool = True, params: dict = None) -> Response:
        return self.__send_request('DELETE', url=url, data=data, verify_response_status=verify_response_status, params=params)

    def log_any_request_response(self):
        if re.compile(".*databucket*").match(self.request.url):
            if self.request.method == "GET":
                self.log_get_databucket_request()
            elif self.request.method == "POST":
                if re.compile(".*reserve*").match(self.request.url):
                    self.log_reserve_databucket_request()
                elif re.compile(".*get*").match(self.request.url):
                    self.log_get_databucket_request()
                else:
                    self.log_post_databucket_request()
            elif self.request.method == "PUT":
                self.log_put_databucket_request()
            elif self.request.method == "DELETE":
                self.log_delete_databucket_request()
            else:
                self.log_databucket_request()
        else:
            self.log_unknown_request()

    def log_request(self):
        try:
            if self.__log_headers:
                headers = '\n'.join(f'{k}: {v}' for k, v in self.request.headers.items())
                headers = f'\n{headers}'
                report_text_info(name='Request headers', body=headers, enable_log=self.__enable_logging, log_console=self.__log_console)

            name = f'{self.request.method} {self.request.url}'
            report_json_info(name=name, body=self.request.body, enable_log=self.__enable_logging, log_console=self.__log_console)
        except:
            print(traceback.format_exc())

    def log_response(self):
        if self.__log_headers:
            headers = '\n'.join(f'{k}: {v}' for k, v in self.response.headers.items())
            headers = f'\n{headers}'
            report_text_info(name='Response headers', body=headers, enable_log=self.__enable_logging, log_console=self.__log_console)

        name = f'Response received in {"%.1f" % self.response.elapsed.total_seconds()} s with status: {self.response.status_code}'
        body = self.response.text
        report_json_info(name=name, body=body, enable_log=self.__enable_logging, log_console=self.__log_console)


    @allure.step('Get test data')
    def log_get_databucket_request(self):
        self.log_request_response()

    @allure.step('Insert test data')
    def log_post_databucket_request(self):
        self.log_request_response()

    @allure.step('Reserve test data')
    def log_reserve_databucket_request(self):
        self.log_request_response()

    @allure.step('Update test data')
    def log_put_databucket_request(self):
        self.log_request_response()

    @allure.step('Remove test data')
    def log_delete_databucket_request(self):
        self.log_request_response()

    @allure.step('Databucket request')
    def log_databucket_request(self):
        self.log_request_response()

    @allure.step('Unknown request')
    def log_unknown_request(self):
        self.log_request_response()

    def log_request_response(self):
        self.log_request()
        self.log_response()


def report_text_info(name: str, body: str = ' ', enable_log: bool = False, log_console: bool = False):
    log.info(f'\n{name}:\n{body}\n')

    if enable_log:
        try:
            allure.attach(body=body, name=name, attachment_type=allure.attachment_type.TEXT)
        except:
            pass

    if log_console:
        print(f'\n{name}:\n{body}\n')


def report_json_info(name: str, body: str, enable_log: bool = False, log_console: bool = False):
    log.info(f'\n{name}:\n{body}\n')

    if enable_log:
        try:
            if body:
                beauty_body = beautify_json(body)
                allure.attach(body=beauty_body, name=name, attachment_type=allure.attachment_type.JSON)
            else:
                allure.attach(body='-- no body --', name=name, attachment_type=allure.attachment_type.TEXT)
        except:
            pass

    if log_console:
        print(f'\n{name}:\n{body}\n')  # log into console


def beautify_json(text_or_dict):
    try:
        if isinstance(text_or_dict, dict):
            return json.dumps(text_or_dict, indent=2, sort_keys=False)
        else:
            return json.dumps(json.loads(text_or_dict), indent=2, sort_keys=False)
    except Exception as e:
        raise AssertionError(f'Bad JSON string:\n{text_or_dict}\n{e.args}')
