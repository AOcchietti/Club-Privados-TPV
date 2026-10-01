# Auth Testing Playbook — Weed Lemon POS

## Step 1: MongoDB verification
```
mongosh
use test_database
db.users.find({role: "admin"}).pretty()
db.users.findOne({role: "admin"}, {password_hash: 1})
```
Verify: bcrypt hash starts with `$2b$`; socios have member_number WL-XXXX and no password_hash.

## Step 2: API testing
```
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '"' -f2 | cut -d '=' -f2)
curl -c /tmp/cookies.txt -X POST $API/api/auth/login -H "Content-Type: application/json" -d '{"email":"admin@weedlemon.es","password":"admin123"}'
curl -b /tmp/cookies.txt $API/api/auth/me
curl -b /tmp/cookies.txt $API/api/products
```
Login returns the user object + token and sets httpOnly cookies; /me returns the same user.

## Step 3: Role checks
- cajero@weedlemon.es / cajero123 CAN list products and sell, CANNOT access /api/activity (403) or create staff.
- socio emails cannot login (403 "solo para el equipo").
