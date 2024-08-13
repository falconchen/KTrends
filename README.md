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

##传参数：如v2ex

```
url：https://v2ex.com/t/1056911
选择器：div.topic_content,div[id^="r_"]
```

```
curl -X 'GET' \
  'http://localhost:8000/fetch_url?url=https%3A%2F%2Fv2ex.com%2Ft%2F1056911&selector=div.topic_content%2Cdiv%5Bid%5E%3D%22r_%22%5D' \
  -H 'accept: application/json'
  ```