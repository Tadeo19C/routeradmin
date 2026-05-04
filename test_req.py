import requests

session = requests.Session()
login_url = 'http://localhost/accounts/login/'
response = session.get(login_url)
csrftoken = session.cookies.get('csrftoken', '')

payload = {
    'username': 'kakaroto',
    'password': 'password123',
    'csrfmiddlewaretoken': csrftoken,
    'next': '/router/list/'
}

res = session.post(login_url, data=payload)
print("Login status:", res.status_code)

res2 = session.get('http://localhost/router/list/')
print("List status:", res2.status_code)

if "Router-Core-01" in res2.text:
    print("Found Router-Core-01!")

# Let's hit the view that was modified
res_detail = session.get('http://localhost/router/details/?uuid=3e082a93-ec6d-4959-af25-179836362f6b') # Or we can fetch uuid from the list
if res_detail.status_code == 500:
    print("500 ERROR CAUGHT")
    open("error.html", "w", encoding="utf-8").write(res_detail.text)
else:
    print("Details page status:", res_detail.status_code)
