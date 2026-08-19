---
description: Iniciar TalentFlow (100% Rust Nativo - Cero Python)
---

Sigue estos pasos en orden para iniciar TalentFlow en Rust nativo:

1. Limpiar procesos residuales de Chrome y bloqueos
// turbo
```bash
rm -f user_data*/SingletonLock && pkill -9 -f chrome || true
```

2. Tarea 1: Verificar Sesión e Identidad en LinkedIn (Rust Nativo)
// turbo
```bash
cargo run -- step1-auth --profile user_data_safe
```

3. Iniciar el Dashboard en Vivo (Axum en puerto 8001)
// turbo
```bash
cargo run -- dashboard
```

El dashboard estará disponible en: http://localhost:8001
