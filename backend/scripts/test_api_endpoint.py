import requests

try:
    r = requests.get('http://localhost:8000/health')
    print('Health:', r.status_code, r.text)
except Exception as e:
    print('Error connecting to backend on port 8000:', e)

try:
    r = requests.put('http://localhost:8000/api/v1/auth/update-profile', json={'name': 'test', 'email': 'test@test.com', 'store_images': True})
    print('Update profile without auth:', r.status_code, r.text[:200])
except Exception as e:
    print('Error sending PUT to backend:', e)
