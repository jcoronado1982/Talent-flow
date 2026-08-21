# 🔄 Guía de Gestión y Alternancia de Perfiles de LinkedIn

Este documento explica cómo están estructurados los perfiles de usuario en **TalentFlow** y el procedimiento exacto para alternar o revertir entre la **Cuenta de Pruebas** (`safe.jcoronado@gmail.com`) y la **Cuenta Principal / Producción** (`email.coronado@gmail.com`).

---

## 📌 1. Mapeo de Identidades y Rutas en el Sistema

| Parámetro | Cuenta de Pruebas (`safe`) | Cuenta Principal / Producción (`personal`) |
| :--- | :--- | :--- |
| **Correo Electrónico** | `safe.jcoronado@gmail.com` | `email.coronado@gmail.com` |
| **Perfil en Google Chrome (Linux)** | `~/.config/google-chrome/Profile 1` | `~/.config/google-chrome/Default` |
| **Carpeta de Perfil Local en TalentFlow** | `./user_data_safe` | `./user_data_auth` |
| **LinkedIn URL** | Perfil de pruebas seguro | `https://www.linkedin.com/in/jcoronado1982/` |

---

## 🎯 2. Configuración Actual Activa (Modo Seguro: `safe.jcoronado@gmail.com`)

Actualmente el sistema está configurado para operar con **`safe.jcoronado@gmail.com`**:
1. **`src_rust/services/browser.rs`**: Prioriza `./user_data_safe` como carpeta de sesión.
2. **`src_rust/services/cookie_injector.rs`**: Extrae las cookies primero desde `Profile 1/Cookies`.
3. **`config/credentials.yaml`**: Configurado con `safe.jcoronado@gmail.com`.
4. **`config/profile_config.json`**: Configurado con `safe.jcoronado@gmail.com`.

---

## 🔁 3. Procedimiento para Revertir / Cambiar a `email.coronado@gmail.com`

Cuando el usuario indique cambiar a la cuenta personal (`email.coronado@gmail.com`), realizar los siguientes 3 pasos:

### Paso 1: Actualizar Archivos de Configuración
1. En [`config/credentials.yaml`](file:///home/jcoronado/Desktop/dev/TalentFlow/config/credentials.yaml):
   ```yaml
   linkedin:
     email: "tu_email@ejemplo.com"
     password: "TU_PASSWORD"
   gmail:
     email: "tu_email@ejemplo.com"
   ```
2. En [`config/profile_config.json`](file:///home/jcoronado/Desktop/dev/TalentFlow/config/profile_config.json):
   ```json
   "personal_info": {
     "full_name": "Jesus Coronado",
     "email": "email.coronado@gmail.com",
     "linkedin_url": "https://www.linkedin.com/in/jcoronado1982/"
   }
   ```

### Paso 2: Actualizar Prioridad de Perfiles en Rust
1. En [`src_rust/services/browser.rs`](file:///home/jcoronado/Desktop/dev/TalentFlow/src_rust/services/browser.rs):
   Asegurar que `user_data_auth` tenga prioridad:
   ```rust
   let user_data_path = if current_dir.join("user_data_auth").exists() {
       current_dir.join("user_data_auth")
   } else if current_dir.join("user_data_safe").exists() {
       current_dir.join("user_data_safe")
   } else {
       current_dir.join("user_data")
   };
   ```
2. En [`src_rust/services/cookie_injector.rs`](file:///home/jcoronado/Desktop/dev/TalentFlow/src_rust/services/cookie_injector.rs):
   Poner `Default/Cookies` en primer lugar:
   ```rust
   let potential_paths = vec![
       PathBuf::from(&home).join(".config/google-chrome/Default/Cookies"),
       PathBuf::from(&home).join(".config/google-chrome/Profile 1/Cookies"),
   ];
   ```

### Paso 3: Recompilar y Reiniciar el Servidor
```bash
cargo build
fuser -k 8001/tcp || true
./target/debug/talentflow &
```

---

## 🔒 4. Reglas Inmutables (Human Stealth Mode)
Cualquiera que sea la cuenta seleccionada, **el navegador SIEMPRE debe lanzarse en modo humano puro** (`tokio::process::Command` + WebSocket CDP) sin banderas `--enable-automation` para evitar bloqueos de Google / LinkedIn.
