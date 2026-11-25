"""Enviar avisos a personas por su número de control o por su rol."""


def chats_de(db, no_control):
    return [r[0] for r in db.execute("SELECT chat_id FROM vinculos WHERE no_control=?", (no_control,))]


def avisar(db, tg, no_control, texto, botones=None):
    chats = chats_de(db, no_control)
    for chat in chats:
        tg.enviar(chat, texto, botones)
    return len(chats)


def avisar_rol(db, tg, rol, texto, botones=None, departamento=None):
    sql, params = "SELECT no_control FROM usuarios WHERE rol=?", [rol]
    if departamento:
        sql, params = sql + " AND departamento=?", params + [departamento]
    return sum(avisar(db, tg, r[0], texto, botones) for r in db.execute(sql, params).fetchall())


def ya_enviado(db, clave, ahora_txt):
    """Marca un aviso automático como enviado. Devuelve True si ya se había mandado antes."""
    cur = db.execute("INSERT OR IGNORE INTO enviados VALUES (?,?)", (clave, ahora_txt))
    db.commit()
    return cur.rowcount == 0
