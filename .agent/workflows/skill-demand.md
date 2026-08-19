---
description: Construir o actualizar la tabla skill_demand con el conteo de skills pedidos en las ofertas de trabajo.
---

# 📊 Skill Demand — Conteo de Skills por Oferta

Este workflow extrae los skills de **todas las ofertas** en la base de datos y construye la tabla `skill_demand`, que lleva un conteo acumulativo de cuántas veces se solicita cada skill. Es útil para analizar tendencias del mercado laboral y priorizar habilidades en el perfil del candidato.

---

## Tabla generada: `skill_demand`

| Columna    | Tipo     | Descripción                                  |
|------------|----------|----------------------------------------------|
| `skill`    | TEXT PK  | Nombre del skill normalizado (minúsculas)    |
| `count`    | INTEGER  | Nº de ofertas que mencionan ese skill        |
| `last_seen`| DATETIME | Última oferta procesada que lo mencionó      |

---

## Uso

### Opción A — Construcción inicial (desde cero)
Borra la tabla anterior y la reconstruye con todos los jobs actuales.
// turbo
```bash
./.venv3.13/bin/python scratch/build_skill_demand.py --reset
```

### Opción B — Actualización incremental
Suma los skills de los jobs nuevos/existentes sin borrar el historial.
```bash
./.venv3.13/bin/python scratch/build_skill_demand.py
```

### Opción C — Ver top N skills
Muestra el ranking final con más o menos entradas (default: 20).
```bash
./.venv3.13/bin/python scratch/build_skill_demand.py --reset --top 30
```

---

## Consultar directamente en SQLite

Ver top 10 skills más demandados:
```bash
sqlite3 talentflow.db "SELECT skill, count FROM skill_demand ORDER BY count DESC LIMIT 10;"
```

Ver si un skill específico existe:
```bash
sqlite3 talentflow.db "SELECT * FROM skill_demand WHERE skill = 'python';"
```

---

## Notas importantes

- Los skills se normalizan a **minúsculas** y se recortan espacios.
- El separador esperado en la columna `jobs.skills` es **coma** (`,`).
- Usar `--reset` cuando se haya modificado la lógica del parser o se quiera recontar desde cero.
- Sin `--reset`, cada ejecución **suma** al conteo existente (útil para actualizaciones periódicas).
- El script vive en `scratch/build_skill_demand.py` y es independiente del bot principal.
