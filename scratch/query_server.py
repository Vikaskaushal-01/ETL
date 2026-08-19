import urllib.request
import urllib.error

url = "http://127.0.0.1:8000/api/v1/pipeline/flowchart?batch_id=batch_5dc7eafa"
try:
    with urllib.request.urlopen(url) as response:
        print("Status code:", response.status)
        print("Headers:")
        for k, v in response.getheaders():
            print(f"  {k}: {v}")
        content = response.read()
        print("Content length:", len(content))
        print("First 200 bytes of content:")
        print(content[:200])
except urllib.error.HTTPError as e:
    print("HTTP Error status:", e.code)
    print("HTTP Error response:", e.read().decode('utf-8'))
except Exception as e:
    print("Error:", e)
