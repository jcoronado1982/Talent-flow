---
description: Construir o actualizar la tabla companies con el resumen de empresas detectadas en las ofertas.
---

# 🏢 Company List — Resumen de Empresas

Este workflow escanea todas las ofertas de trabajo para identificar empresas únicas y llevar un registro de cuántas ofertas publica cada una y cuándo se vio su última vacante.

---

## Tabla generada: `companies`

| Columna      | Tipo        | Descripción                                      |
|--------------|-------------|--------------------------------------------------|
| `name`       | TEXT PK     | Nombre de la empresa (normalizado)               |
| `job_count`  | INTEGER     | Total de ofertas encontradas para esta empresa   |
| `last_seen`  | DATETIME    | Fecha de la oferta más reciente                  |
| `created_at` | DATETIME    | Fecha de creación del registro en esta tabla     |

---

## Uso

### Opción A — Inicialización completo (Reset)
Borra los datos de la tabla de empresas y vuelve a contar todo desde la tabla de jobs.
// turbo
```bash
./.venv3.13/bin/python scratch/build_company_list.py --reset
```

### Opción B — Actualización rápida
Suma los jobs nuevos a los conteos existentes sin borrar el historial previo.
```bash
./.venv3.13/bin/python scratch/build_company_list.py
```

---

## Consultar datos rápidamente

Ver el Top 20 de empresas que más publican:
```bash
sqlite3 talentflow.db "SELECT name, job_count FROM companies ORDER BY job_count DESC LIMIT 20;"
```

---

## Notas importantes

- El script realiza una **normalización básica** (trimming) para evitar duplicados por espacios extra.
- Si una empresa tiene nombre vacío o "Unknown", se agrupa bajo el nombre "Unknown".
- Puedes ejecutar este proceso periódicamente para mantener actualizado el ranking de empresas.
