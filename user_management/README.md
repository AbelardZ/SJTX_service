# 用户管理系统
## 概述
网站设置可选登录
用户信息包括用户名和密码
用户分为四种类型
- 未登录
- 普通用户
- 会员用户
- 管理员用户
每个类型的用户包含以下信息：
- user_name:
- type:normal/vip/amdin
- password:
- email:
- phone_number(opt):

不同类型的用户访问权限不同
使用mongodb存储用户信息