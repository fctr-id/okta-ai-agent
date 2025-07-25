#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('c:/Users/Dharanidhar/Desktop/github-repos/okta-ai-agent/sqlite_db/okta_sync.db')
cursor = conn.cursor()

print('=== CHECKING DAN USER ===')
cursor.execute('SELECT okta_id, email, first_name, last_name FROM users WHERE email = ?', ('dan@fctr.io',))
dan_user = cursor.fetchone()
print(f'Dan user: {dan_user}')

if dan_user:
    dan_id = dan_user[0]
    
    print(f'\n=== GROUPS FOR DAN ({dan_id}) ===')
    cursor.execute('''
        SELECT COUNT(*) FROM user_group_memberships ugm 
        JOIN groups g ON ugm.group_okta_id = g.okta_id 
        WHERE ugm.user_okta_id = ? AND g.is_deleted = 0
    ''', (dan_id,))
    group_count = cursor.fetchone()[0]
    print(f'Dan group count: {group_count}')
    
    print(f'\n=== APPS FOR DAN ({dan_id}) ===')
    cursor.execute('''
        SELECT COUNT(*) FROM user_application_assignments uaa 
        JOIN applications a ON uaa.application_okta_id = a.okta_id 
        WHERE uaa.user_okta_id = ? AND a.status = "ACTIVE" AND a.is_deleted = 0
    ''', (dan_id,))
    app_count = cursor.fetchone()[0]
    print(f'Dan direct app count: {app_count}')
    
    print(f'\n=== CHECKING AIDEN USER ===')
    cursor.execute('SELECT okta_id, email, first_name, last_name FROM users WHERE email = ?', ('aiden.garcia@fctr.io',))
    aiden_user = cursor.fetchone()
    print(f'Aiden user: {aiden_user}')
    
    if aiden_user:
        aiden_id = aiden_user[0]
        
        print(f'\n=== GROUPS FOR AIDEN ({aiden_id}) ===')
        cursor.execute('''
            SELECT COUNT(*) FROM user_group_memberships ugm 
            JOIN groups g ON ugm.group_okta_id = g.okta_id 
            WHERE ugm.user_okta_id = ? AND g.is_deleted = 0
        ''', (aiden_id,))
        aiden_group_count = cursor.fetchone()[0]
        print(f'Aiden group count: {aiden_group_count}')

conn.close()
