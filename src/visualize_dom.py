
import os
import sys
from html.parser import HTMLParser

class DOMNode:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.parent = None
        self.text = ""

    @property
    def classes(self):
        return self.attrs.get('class', '').split()

    @property
    def id(self):
        return self.attrs.get('id', '')

class VisualizerParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = DOMNode('root', [])
        self.current = self.root
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        if tag in ['br', 'img', 'meta', 'link']:
            return # Skip self-closing void elements for tree logic simplicity in this quick script
        node = DOMNode(tag, attrs)
        node.parent = self.current
        self.current.children.append(node)
        self.current = node
        self.nodes.append(node)

    def handle_endtag(self, tag):
        if tag in ['br', 'img', 'meta', 'link']:
            return
        if self.current.parent:
            self.current = self.current.parent

    def handle_data(self, data):
        if self.current:
            self.current.text = data.strip()

def print_tree(node, depth=0, max_depth_below=3, target_depth=None, file=sys.stdout):
    if depth > 100: return # Safety
    
    indent = "  " * depth
    
    # Format representation
    repr_str = f"<{node.tag}"
    if node.id:
        repr_str += f" id='{node.id}'"
    if node.classes:
        repr_str += f" class='{'.'.join(node.classes)}'"
    repr_str += ">"
    
    print(f"{indent}{repr_str}", file=file)
    
    # Don't go too deep unless it's interesting
    if target_depth is not None and depth > target_depth + max_depth_below:
        if node.children:
            print(f"{indent}  ... ({len(node.children)} children hidden)", file=file)
        return

    child_limit = 5 # Show max 5 siblings to keep map readable
    for i, child in enumerate(node.children):
        if i >= child_limit:
            print(f"{indent}  ... (+{len(node.children)-child_limit} more siblings)", file=file)
            break
        print_tree(child, depth+1, max_depth_below, target_depth, file)

def main():
    filepath = "linkedin_debug.html"
    if not os.path.exists(filepath):
        print("No debug file found.")
        return

    print("Parsing HTML... this may take a moment...")
    parser = VisualizerParser()
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        parser.feed(content)

    # Find the interesting node (The Job List)
    print("Searching for job list container...")
    target_node = None
    
    # Breadth-first search for the node containing scaffold-layout__list-item
    queue = [parser.root]
    while queue:
        node = queue.pop(0)
        
        # Check if this node IS a job item
        is_item = 'scaffold-layout__list-item' in node.classes
        
        if is_item and node.parent:
            target_node = node.parent
            break
        
        queue.extend(node.children)

    if target_node:
        print(f"\n✅ Found Job List Container: <{target_node.tag} class='{' '.join(target_node.classes)}'>")
        print("\n=== DOM MAP (Focused on List) ===\n")
        
        # Walk up to find a good root for display (e.g. 3 levels up)
        display_root = target_node
        levels_up = 0
        while display_root.parent and display_root.parent.tag != 'body' and levels_up < 4:
            display_root = display_root.parent
            levels_up += 1
            
        print_tree(display_root, depth=0, max_depth_below=4, target_depth=levels_up)
        
        # Save to file
        with open("dom_map.txt", "w") as f:
             print_tree(display_root, depth=0, max_depth_below=4, target_depth=levels_up, file=f)
        print("\n✅ Map saved to dom_map.txt")
             
    else:
        print("❌ Could not find search results list in the snapshot.")

if __name__ == "__main__":
    main()
