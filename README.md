# Appium Server管理端

测试服务器通过Appium Server和手机建立连接(可以通过手机wifi连接到公司内网)，执行测试用例。项目采用python语言编写，基于flask web框架。主要提供的功能有：

1. adb连接管理，根据地址和端口建立和手机的adb连接。

2. appium server管理和维护。获取设备上连接的手机数目、建立和断开appium server。

3. 分配手机连接端口

4. 上传和下载apk包。
