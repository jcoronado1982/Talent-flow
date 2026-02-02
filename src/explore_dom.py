
import os
import sys
from html.parser import HTMLParser

# --- DOM STRUCTURE ---
class DOMNode:
    def __init__(self, tag, attrs, parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.parent = parent
        self.text = ""
        self.id = self.attrs.get('id', '')
        self.classes = self.attrs.get('class', '').split()

    def __repr__(self):
        desc = f"<{self.tag}"
        if self.id: desc += f" id='{self.id}'"
        if self.classes: desc += f" class='{'.'.join(self.classes)}'"
        desc += ">"
        return desc

    def get_path(self):
        path = []
        curr = self
        while curr:
            path.append(curr.tag)
            curr = curr.parent
        return "/".join(reversed(path))

class DOMBuilder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = DOMNode('document', {}, None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        if tag in ['br', 'img', 'meta', 'link', 'input', 'hr']: # Void elements
            node = DOMNode(tag, attrs, self.current)
            self.current.children.append(node)
            return

        node = DOMNode(tag, attrs, self.current)
        self.current.children.append(node)
        self.current = node

    def handle_endtag(self, tag):
        if tag in ['br', 'img', 'meta', 'link', 'input', 'hr']: return
        if self.current.parent:
            self.current = self.current.parent

    def handle_data(self, data):
        if self.current and data.strip():
            self.current.text = data.strip()

# --- INTERACTIVE SHELL ---
def run_explorer():
    filepath = "linkedin_debug.html"
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return

    print("⏳ Cargando DOM... (puede tardar unos segundos)")
    parser = DOMBuilder()
    with open(filepath, "r", encoding="utf-8") as f:
        parser.feed(f.read())

    # Start looking for the interesting part generally (body)
    current = parser.root
    # Try to jump to body if exists
    for child in current.children:
        if child.tag == 'html':
            for sub in child.children:
                if sub.tag == 'body':
                    current = sub
                    break

    while True:
        print("\n" + "="*50)
        print(f"📍 UBICACIÓN: {current.get_path()}")
        print(f"👁️  NODO ACTUAL: {current}")
        if current.text:
            print(f"📝 TEXTO: {current.text[:100]}...")
        print("-" * 50)
        
        # List Children
        print(f"📂 HIJOS ({len(current.children)}):")
        for i, child in enumerate(current.children):
            preview = f"[{i}] {child}"
            # Highlight interesting nodes
            if 'scaffold-layout__list-item' in child.classes:
                preview += "  🌟 (ITEM EMPLEO)"
            elif 'jobs-search-results-list' in child.tag or 'ul' in child.tag:
                 if len(child.children) > 10:
                     preview += "  📦 (POSIBLE LISTA)"
            
            # Truncate
            if len(preview) > 80: preview = preview[:77] + "..."
            print(f"  {preview}")

        print("\nCOMANDOS: [número] Entrar | [u] Subir | [/] Buscar Clase | [q] Salir")
        cmd = input("👉 Tu orden: ").strip().lower()

        if cmd == 'q':
            break
        elif cmd == 'u':
            if current.parent:
                current = current.parent
            else:
                print("⚠️ Ya estás en la raíz.")
        elif cmd.startswith('/'):
            # Search
            query = cmd[1:]
            print(f"🔎 Buscando primer nodo con clase que contenga '{query}'...")
            
            # BFS search
            queue = [parser.root]
            found = None
            while queue:
                n = queue.pop(0)
                if any(query in c for c in n.classes):
                    found = n
                    break
                queue.extend(n.children)
            
            if found:
                current = found
                print(f"✅ Encontrado: {current}")
            else:
                print("❌ No encontrado.")
        
        elif cmd.isdigit():
            idx = int(cmd)
            if 0 <= idx < len(current.children):
                current = current.children[idx]
            else:
                print("⚠️ Índice inválido.")
        else:
            print("❓ Comando no reconocido.")

if __name__ == "__main__":
    run_explorer()
