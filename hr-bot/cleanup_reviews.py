import sqlite3

DB_PATH = "/opt/hr-bot/candidates.db"

review_users = [
    "@gfch3k","@XYL0_0XYL","@vaanyaasleep","@AlecsSpB",
    "@Villora517","@vadim65060","@Andruy28","@V_potoke_Kilimanjaro",
    "@danlav00","@duh_poligona","@g00db7e","@saviorofgothamO_O",
    "@traxodron_24","@wi_shet","@eyesonjewelry","@samokamillica",
    "@aashanfr","@ka_risha3","@shmitk","@Iliya_999999","@iveze",
    "@melnivan","@evuyan","@nagibatel228","@elenash464",
    "@chergintsev","@Sy_rai","@kenguru331","@pilsed",
    "@recruiter_tg","@nemok1rra","@ooot345266",
]

conn = sqlite3.connect(DB_PATH)
deleted = 0
for u in review_users:
    r = conn.execute("DELETE FROM candidates WHERE username = ?", (u,))
    deleted += r.rowcount

conn.commit()
conn.close()
print(f"Удалено {deleted} записей про отзывы")
