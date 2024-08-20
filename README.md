#	KTrends

## 创建项目和虚拟py环境

```
virtualenv -p /Library/Frameworks/Python.framework/Versions/Current/bin/python KTrends
cd /Users/falcon/projects/python/
source KTrends/bin/activate
```

## 运行，默认在8000端口监听
```
uvicorn main:app --reload --port 8000
```

## 传参数：如v2ex

```
url：https://v2ex.com/t/1056911
选择器：div.topic_content,div[id^="r_"]
```

```
curl -X 'GET' \
  'http://localhost:8000/fetch_url?url=https%3A%2F%2Fv2ex.com%2Ft%2F1056911&selector=div.topic_content%2Cdiv%5Bid%5E%3D%22r_%22%5D' \
  -H 'accept: application/json'
  ```

## freeze

``` 
pip freeze >requirements.txt
```

## 部署到服务器
```
pip install -r requirements.txt
```

## 对 serv00
部分包需要特殊安装 orjson, pydantic_core, uvloop, watchfiles

```
cpuset -l 0 pip install -r requirements.txt

```

参考：<https://forum.serv00.com/d/170-no-support-for-python-libraries>
```
cpuset -l 0 pip install numpy
cpuset -l 0 pip install pandas

cpuset -l 0 pip install  orjson
cpuset -l 0 pip install uvloop
cpuset -l 0 pip install pydantic_core
cpuset -l 0 pip install watchfiles

```

## 构建docker 镜像（多架构交叉编译）

```
docker buildx build --platform linux/amd64,linux/arm64 -t falconchen/ktrends:latest --push .

```
文章：
<https://d.cellmean.com/p/caa450dbab14>