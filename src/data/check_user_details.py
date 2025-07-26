import sqlite3

# Connect to the database
conn = sqlite3.connect('sqlite_db/okta_sync.db')
cursor = conn.cursor()

# Check Dan's details (00uropbgtlUuob0uH697)
dan_id = "00uropbgtlUuob0uH697"
aiden_id = "00us049g5koN4Vvb7697"

print("=== DAN'S PROFILE ===")
cursor.execute("SELECT okta_id, email, first_name, last_name, status FROM users WHERE okta_id = ?", (dan_id,))
dan_user = cursor.fetchone()
if dan_user:
    print(f"User: {dan_user[1]} ({dan_user[2]} {dan_user[3]}) - Status: {dan_user[4]}")

# Check Dan's groups
print(f"\n=== DAN'S GROUPS ===")
cursor.execute("""
    SELECT g.name, g.okta_id 
    FROM user_group_memberships ugm 
    JOIN groups g ON ugm.group_okta_id = g.okta_id 
    WHERE ugm.user_okta_id = ?
""", (dan_id,))
dan_groups = cursor.fetchall()
print(f"Dan has {len(dan_groups)} groups:")
for group in dan_groups[:10]:  # Show first 10
    print(f"  - {group[0]}")
if len(dan_groups) > 10:
    print(f"  ... and {len(dan_groups) - 10} more groups")

# Check Dan's applications
print(f"\n=== DAN'S APPLICATIONS ===")
cursor.execute("""
    SELECT DISTINCT a.label, a.okta_id, a.status
    FROM user_application_assignments uaa 
    JOIN applications a ON uaa.application_okta_id = a.okta_id 
    WHERE uaa.user_okta_id = ? AND a.status = 'ACTIVE'
""", (dan_id,))
dan_direct_apps = cursor.fetchall()
print(f"Dan has {len(dan_direct_apps)} direct applications:")
for app in dan_direct_apps:
    print(f"  - {app[0]} ({app[2]})")

# Check Dan's group-based applications
cursor.execute("""
    SELECT DISTINCT a.label, a.okta_id, a.status, g.name as group_name
    FROM user_group_memberships ugm
    JOIN group_application_assignments gaa ON ugm.group_okta_id = gaa.group_okta_id
    JOIN applications a ON gaa.application_okta_id = a.okta_id
    JOIN groups g ON ugm.group_okta_id = g.okta_id
    WHERE ugm.user_okta_id = ? AND a.status = 'ACTIVE'
""", (dan_id,))
dan_group_apps = cursor.fetchall()
print(f"Dan has {len(dan_group_apps)} applications through groups:")
for app in dan_group_apps:
    print(f"  - {app[0]} (via {app[3]})")

print(f"\n=== AIDEN'S PROFILE ===")
cursor.execute("SELECT okta_id, email, first_name, last_name, status FROM users WHERE okta_id = ?", (aiden_id,))
aiden_user = cursor.fetchone()
if aiden_user:
    print(f"User: {aiden_user[1]} ({aiden_user[2]} {aiden_user[3]}) - Status: {aiden_user[4]}")

# Check Aiden's groups
cursor.execute("""
    SELECT g.name, g.okta_id 
    FROM user_group_memberships ugm 
    JOIN groups g ON ugm.group_okta_id = g.okta_id 
    WHERE ugm.user_okta_id = ?
""", (aiden_id,))
aiden_groups = cursor.fetchall()
print(f"Aiden has {len(aiden_groups)} groups")

conn.close()
