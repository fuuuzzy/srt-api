# SRT翻译API服务

## 功能说明

提供SRT字幕文件翻译功能的Web API服务。

## 启动方式

### 1. 直接运行Python脚本

```bash
# 使用默认端口8000
python api_server.py

# 指定端口
python api_server.py --port 9000

# 指定主机和端口
python api_server.py --host 127.0.0.1 --port 9000

# 开发模式（自动重载）
python api_server.py --port 8000 --reload
```

### 2. 使用启动脚本

**Linux/Mac:**
```bash
# 默认端口8000
./start_server.sh

# 指定端口
./start_server.sh 9000

# 指定主机和端口
./start_server.sh 9000 127.0.0.1
```

**Windows:**
```cmd
REM 默认端口8000
start_server.bat

REM 指定端口
start_server.bat 9000

REM 指定主机和端口
start_server.bat 9000 127.0.0.1
```

### 3. 打包后的exe文件

**直接运行exe:**
```cmd
REM 默认端口8000
api_server.exe

REM 指定端口
api_server.exe --port 9000

REM 指定主机和端口
api_server.exe --host 127.0.0.1 --port 9000
```

**使用启动脚本（推荐）:**
```cmd
REM 默认端口8000
start_server_exe.bat

REM 指定端口
start_server_exe.bat 9000

REM 指定主机和端口
start_server_exe.bat 9000 127.0.0.1
```

## 命令行参数

- `--port`: 服务端口号（默认: 8000）
- `--host`: 服务主机地址（默认: 0.0.0.0）
- `--reload`: 启用自动重载（开发模式）

## API接口

### POST /translate

翻译SRT字幕文件

**请求体:**
```json
{
  "srt": "1\n00:00:00,000 --> 00:00:04,100\n你好世界\n",
  "lang": "EN",
  "source_lang": "ZH"
}
```

**响应:**
翻译后的SRT文本（纯文本格式）

### GET /languages

获取支持的语言列表

### GET /

获取API信息

## 日志

所有操作都会在控制台显示详细日志，包括：
- 请求接收时间
- 语言代码标准化
- SRT解析过程
- 翻译API调用
- 处理耗时
- 错误信息

