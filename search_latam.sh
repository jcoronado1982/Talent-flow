#!/bin/bash

echo "================================================="
echo "🚀 CONTINUANDO BÚSQUEDA MASIVA EN LATAM (40 x Rol)"
echo "================================================="
echo "✅ Colombia ya fue procesada (42 vacantes). Saltando..."

echo -e "\n📍 Buscando en Brasil..."
cargo run -- search --limit 40 --country "Brazil"
sleep 5

echo -e "\n📍 Buscando en Argentina..."
cargo run -- search --limit 40 --country "Argentina"
sleep 5

echo -e "\n📍 Buscando en Uruguay..."
cargo run -- search --limit 40 --country "Uruguay"
sleep 5

echo -e "\n📍 Buscando en Chile..."
cargo run -- search --limit 40 --country "Chile"
sleep 5

echo -e "\n📍 Buscando en México..."
cargo run -- search --limit 40 --country "Mexico"

echo "================================================="
echo "✅ BÚSQUEDA MASIVA COMPLETADA."
echo "Puedes ver los resultados en: http://localhost:8001"
echo "================================================="
