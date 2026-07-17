import sqlite3, json

conn = sqlite3.connect('candidates.db')
conn.row_factory = sqlite3.Row

cur = conn.execute("SELECT md.candidate_user_id, md.decision, md.created_at, md.processed, c.username, c.name, c.status, c.subject FROM manager_decisions md LEFT JOIN candidates c ON md.candidate_user_id = c.user_id ORDER BY md.created_at DESC LIMIT 20")
print('=== РЕШЕНИЯ МЕНЕДЖЕРА ===')
for r in cur:
    print(f"uid={r['candidate_user_id']} | @{r['username']} | {r['name']} | decision={r['decision']} | {r['created_at']} | processed={r['processed']} | status={r['status']} | {r['subject']}")

print()
print('=== ВСЕ КАНДИДАТЫ ===')
cur3 = conn.execute("SELECT user_id, username, name, status, subject, score, updated_at FROM candidates ORDER BY updated_at DESC")
for r in cur3:
    print(f"uid={r['user_id']} | @{r['username']} | {r['name']} | {r['status']} | {r['subject']} | score={r['score']} | {r['updated_at']}")
