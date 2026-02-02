
import os
import json
import html as html_lib
from html.parser import HTMLParser

# --- PARSER ---
class DOMNode:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.text = ""

    def to_dict(self):
        return {
            "tag": self.tag,
            "id": self.attrs.get("id", ""),
            "classes": self.attrs.get("class", ""),
            "text": self.text[:50] if self.text else "", # Truncate text
            "children": [c.to_dict() for c in self.children]
        }

class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = DOMNode('document', {})
        self.current = self.root
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if tag in ['br', 'img', 'meta', 'link', 'input', 'hr', 'path', 'rect']: 
            # Self-closing (simplified)
            node = DOMNode(tag, attrs)
            self.current.children.append(node)
            return

        node = DOMNode(tag, attrs)
        self.current.children.append(node)
        self.current = node
        self.stack.append(node)

    def handle_endtag(self, tag):
        if tag in ['br', 'img', 'meta', 'link', 'input', 'hr', 'path', 'rect']: return
        
        if len(self.stack) > 1:
            self.stack.pop()
            self.current = self.stack[-1]

    def handle_data(self, data):
        if self.current and data.strip():
            self.current.text = data.strip().replace("\n", " ")

# --- TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: monospace; background: #f0f0f0; padding: 20px; }
        .tree-node { margin-left: 20px; }
        .tag-line { 
            cursor: pointer; 
            padding: 2px; 
            border-radius: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .tag-line:hover { background: #e0e0e0; }
        .tag-name { color: #881280; font-weight: bold; }
        .attr-name { color: #994500; }
        .attr-val { color: #1a1aa6; }
        .text-content { color: #333; font-style: italic; }
        .toggle-btn {
            display: inline-block;
            width: 12px;
            color: #666;
            font-weight: bold;
            text-align: center;
            margin-right: 5px;
        }
        .children-container { display: none; border-left: 1px solid #ccc; }
        .expanded > .children-container { display: block; }
        .expanded > .tag-line > .toggle-btn { transform: rotate(90deg); display: inline-block; }
        
        /* Highlight specific interesting nodes */
        .highlight-job { background: #e6fffa; border: 1px solid #00aaaa; }
    </style>
</head>
<body>
    <h2>🔍 DOM Snapshot Viewer</h2>
    <p>Click tags to expand/collapse. This is a static view of the captured HTML.</p>
    <div id="root"></div>

    <script>
        const domData = __JSON_DATA__;

        function renderNode(node) {
            const container = document.createElement('div');
            container.className = 'tree-node';

            // Tag Line
            const tagLine = document.createElement('div');
            tagLine.className = 'tag-line';
            
            // Toggle
            const toggle = document.createElement('span');
            toggle.className = 'toggle-btn';
            toggle.textContent = node.children.length > 0 ? '▶' : ' ';
            tagLine.appendChild(toggle);

            // Tag Name
            const tagName = document.createElement('span');
            tagName.className = 'tag-name';
            tagName.textContent = "<" + node.tag;
            tagLine.appendChild(tagName);

            // Attributes (ID/Class only for clean view)
            if (node.id) {
                const sp = document.createElement('span');
                sp.innerHTML = ` <span class="attr-name">id</span>=<span class="attr-val">"${node.id}"</span>`;
                tagLine.appendChild(sp);
            }
            if (node.classes) {
                const sp = document.createElement('span');
                // Truncate ultra long classes
                let cls = node.classes;
                if (cls.length > 50) cls = cls.substring(0, 50) + "...";
                sp.innerHTML = ` <span class="attr-name">class</span>=<span class="attr-val">"${cls}"</span>`;
                tagLine.appendChild(sp);
                
                // Auto-expand relevant nodes
                if (node.classes.includes('scaffold-layout__list-item')) {
                    tagLine.style.backgroundColor = '#ffffaa'; // Highlight items
                }
            }
            tagLine.appendChild(document.createTextNode(">"));
            
            // Text
            if (node.text) {
                const txt = document.createElement('span');
                txt.className = 'text-content';
                txt.textContent = " " + node.text;
                tagLine.appendChild(txt);
            }

            container.appendChild(tagLine);

            // Children
            if (node.children.length > 0) {
                const childrenContainer = document.createElement('div');
                childrenContainer.className = 'children-container';
                
                // Lazy render children on first click would be better for huge DOMs, 
                // but for simplicity we render struct and hide via CSS.
                // Caution: Recursion limit. 
                
                // Optimization: Don't render huge subtrees immediately? 
                // Store children data in a property and render on expand?
                childrenContainer._childrenData = node.children;
                childrenContainer._rendered = false;
                
                container.appendChild(childrenContainer);

                tagLine.onclick = function(e) {
                    e.stopPropagation();
                    container.classList.toggle('expanded');
                    toggle.textContent = container.classList.contains('expanded') ? '▼' : '▶';
                    
                    if (container.classList.contains('expanded') && !childrenContainer._rendered) {
                        // Render children now (Performance fix)
                        childrenContainer._childrenData.forEach(child => {
                            childrenContainer.appendChild(renderNode(child));
                        });
                        childrenContainer._rendered = true;
                    }
                };
                
                // Auto-expand interesting parts
                if (node.tag === 'html' || node.tag === 'body' || (node.classes && node.classes.includes('scaffold-layout__list-container'))) {
                     container.classList.add('expanded');
                     toggle.textContent = '▼';
                     // Pre-render immediate interesting children
                     childrenContainer._childrenData.forEach(child => {
                        childrenContainer.appendChild(renderNode(child));
                     });
                     childrenContainer._rendered = true;
                }
            }

            return container;
        }

        const rootEl = document.getElementById('root');
        // Skip document root wrapper
        rootEl.appendChild(renderNode(domData.children[0])); 

    </script>
</body>
</html>
"""

def generate_viewer():
    filepath = "linkedin_debug.html"
    if not os.path.exists(filepath):
        print("❌ File not found.")
        return

    print("⏳ Analizando HTML (esto toma unos segundos)...")
    parser = TreeBuilder()
    with open(filepath, "r", encoding="utf-8") as f:
        parser.feed(f.read())

    print("⏳ Generando viewer interactivo...")
    # Convert tree to JSON
    # Note: DOM might be huge. We rely on browser JS to handle the object.
    # Python recursion limit check
    sys.setrecursionlimit(5000)
    
    # Extract just the html node (skip the fake root)
    # usually parser.root.children[0] is DOCTYPE or HTML
    try:
        json_str = json.dumps(parser.root.to_dict())
    except Exception as e:
        print(f"Error serializing DOM: {e}")
        return

    final_html = HTML_TEMPLATE.replace("__JSON_DATA__", json_str)
    
    out_path = "dom_viewer.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"\n✅ Viewer Generado: {os.path.abspath(out_path)}")
    print("👉 Abre ese archivo en tu navegador (doble click) para explorar el DOM dinámicamente.")

if __name__ == "__main__":
    import sys
    generate_viewer()
