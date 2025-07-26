import sqlite3

# Connect to the database
conn = sqlite3.connect('sqlite_db/okta_sync.db')
cursor = conn.cursor()

# Check for dan and aiden users
print("Looking for dan@fctr.io and aiden.garcia@fctr.io...")
cursor.execute("SELECT okta_id, email, first_name, last_name FROM users WHERE email LIKE '%dan%' OR email LIKE '%aiden%'")
results = cursor.fetchall()

print(f"Found {len(results)} users:")
for r in results:
    print(f"  {r[1]} ({r[2]} {r[3]}) - ID: {r[0]}")

# Also check for any users with fctr.io domain
print("\nAll fctr.io users:")
cursor.execute("SELECT okta_id, email, first_name, last_name FROM users WHERE email LIKE '%fctr.io%'")
fctr_results = cursor.fetchall()
for r in fctr_results:
    print(f"  {r[1]} ({r[2]} {r[3]}) - ID: {r[0]}")

conn.close()
