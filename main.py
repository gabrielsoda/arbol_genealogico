"""
Interactive family tree editor using PyQt6 and a JSON backend.

Features:
- Load/save family data from/to a JSON file (same structure used earlier).
- Interactive QGraphicsView with draggable nodes, edges that update when nodes move.
- Zoom (wheel), pan (middle mouse / space+drag), node hover tooltip showing description.
- Context menu on node: Edit person, Add child, Delete person.
- Auto-layout (simple top-down generation-based layout).

Requirements:
    pip install PyQt6

Run:
    python interactive_tree_pyqt.py

The file expects a `data.json` in the same folder. If none exists it starts empty.

This is a single-file starter — you can extend it (better dialogs, validation, undo, export, richer styling).
"""

from __future__ import annotations
import json
import os
import math
from typing import List, Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

DATA_FILE = "data.json"

# ------------------
# Data model
# ------------------

class FamilyModel:
    def __init__(self, filename: str = DATA_FILE):
        self.filename = filename
        self.people: List[Dict] = []
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            with open(self.filename, "r", encoding="utf-8") as f:
                self.people = json.load(f)
        else:
            self.people = []

    def save(self):
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.people, f, ensure_ascii=False, indent=4)

    def generate_id(self) -> int:
        return max((p.get("id", 0) for p in self.people), default=0) + 1

    def add_person(self, name: str, dob: str = "", description: str = "", parents: Optional[List[int]] = None, children: Optional[List[int]] = None) -> int:
        new_id = self.generate_id()
        person = {
            "id": new_id,
            "nombre": name,
            "fecha_nacimiento": dob,
            "padres": parents or [],
            "hijos": children or [],
            "descripcion": description,
            # optional position for later saving/restoring
            "x": None,
            "y": None
        }
        self.people.append(person)
        # maintain bidirectional links
        for pid in person["padres"]:
            p = self.get(pid)
            if p and new_id not in p.get("hijos", []):
                p.setdefault("hijos", []).append(new_id)
        for cid in person["hijos"]:
            c = self.get(cid)
            if c and new_id not in c.get("padres", []):
                c.setdefault("padres", []).append(new_id)
        self.save()
        return new_id

    def get(self, id_: int) -> Optional[Dict]:
        return next((p for p in self.people if p.get("id") == id_), None)

    def update_person(self, id_: int, **kwargs):
        p = self.get(id_)
        if not p:
            return False
        # update simple fields
        for k in ("nombre", "fecha_nacimiento", "descripcion"):
            if k in kwargs and kwargs[k] is not None:
                p[k] = kwargs[k]
        # update parents/hijos with consistency
        if "padres" in kwargs and kwargs["padres"] is not None:
            new_parents = kwargs["padres"]
            # remove old backrefs
            for old_parent_id in list(p.get("padres", [])):
                if old_parent_id not in new_parents:
                    parent = self.get(old_parent_id)
                    if parent and p["id"] in parent.get("hijos", []):
                        parent["hijos"].remove(p["id"])                
            p["padres"] = new_parents
            for parent_id in new_parents:
                parent = self.get(parent_id)
                if parent and p["id"] not in parent.get("hijos", []):
                    parent.setdefault("hijos", []).append(p["id"])        
        if "hijos" in kwargs and kwargs["hijos"] is not None:
            new_children = kwargs["hijos"]
            for old_child_id in list(p.get("hijos", [])):
                if old_child_id not in new_children:
                    child = self.get(old_child_id)
                    if child and p["id"] in child.get("padres", []):
                        child["padres"].remove(p["id"])                
            p["hijos"] = new_children
            for child_id in new_children:
                child = self.get(child_id)
                if child and p["id"] not in child.get("padres", []):
                    child.setdefault("padres", []).append(p["id"])        
        self.save()
        return True

    def delete_person(self, id_: int):
        p = self.get(id_)
        if not p:
            return False
        # remove references
        for other in self.people:
            if id_ in other.get("padres", []):
                other["padres"].remove(id_)
            if id_ in other.get("hijos", []):
                other["hijos"].remove(id_)
        self.people = [x for x in self.people if x.get("id") != id_]
        self.save()
        return True


# ------------------
# Graphics items
# ------------------

class EdgeItem(QtWidgets.QGraphicsLineItem):
    def __init__(self, src: 'NodeItem', dst: 'NodeItem'):
        super().__init__()
        self.src = src
        self.dst = dst
        pen = QtGui.QPen(QtGui.QColor(90, 90, 90))
        pen.setWidth(2)
        self.setPen(pen)
        self.setZValue(-1)
        self.update_pos()

    def update_pos(self):
        p1 = self.src.center()
        p2 = self.dst.center()
        self.setLine(p1.x(), p1.y(), p2.x(), p2.y())


class NodeItem(QtWidgets.QGraphicsEllipseItem):
    RADIUS = 50

    def __init__(self, person: Dict, model: FamilyModel):
        r = NodeItem.RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.person = person
        self.model = model
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges |
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self.edges: List[EdgeItem] = []
        self.text = QtWidgets.QGraphicsTextItem(self.label_text(), self)
        self.text.setTextWidth(r * 1.6)
        self.text.setDefaultTextColor(QtGui.QColor(20, 20, 20))
        self.text.setPos(-r * 0.8, -10)
        self.setBrush(QtGui.QBrush(QtGui.QColor(200, 230, 255)))
        self.setPen(QtGui.QPen(QtGui.QColor(60, 120, 180), 2))

    def label_text(self):
        name = self.person.get("nombre", "")
        dob = self.person.get("fecha_nacimiento", "")
        return f"{name}\n{dob}" if dob else name

    def center(self) -> QtCore.QPointF:
        return self.scenePos()

    def add_edge(self, edge: EdgeItem):
        self.edges.append(edge)

    def remove_edge(self, edge: EdgeItem):
        if edge in self.edges:
            self.edges.remove(edge)
    
    def hoverEnterEvent(self, event):
        desc = f"{self.name}\n{self.data.get('description', '')}"

        # Obtener posición de pantalla en formato QPoint
        pos = event.screenPos()
        if hasattr(pos, "toPoint"):  # Si ya es un QPointF con toPoint()
            pos = pos.toPoint()
        elif hasattr(pos, "toPointF"):  # Si es un QPoint y tiene toPointF()
            pos = pos.toPointF().toPoint()

        QtWidgets.QToolTip.showText(pos, desc)
        super().hoverEnterEvent(event)


    def hoverLeaveEvent(self, event):
        QtWidgets.QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for e in self.edges:
                e.update_pos()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        # quick edit
        dlg = EditPersonDialog(self.person, self.model)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            # refresh label
            self.text.setPlainText(self.label_text())
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu()
        edit_action = menu.addAction("Editar persona")
        add_child_action = menu.addAction("Agregar hijo")
        delete_action = menu.addAction("Eliminar persona")
        action = menu.exec(event.screenPos().toPoint())
        if action == edit_action:
            dlg = EditPersonDialog(self.person, self.model)
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.text.setPlainText(self.label_text())
        elif action == add_child_action:
            name, ok = QtWidgets.QInputDialog.getText(None, "Nuevo hijo", "Nombre del hijo:")
            if ok and name:
                child_id = self.model.add_person(name)
                # set relationships
                # add child id to this person's hijos and this id to child's padres
                if child_id not in self.person.get("hijos", []):
                    self.person.setdefault("hijos", []).append(child_id)
                child = self.model.get(child_id)
                child.setdefault("padres", []).append(self.person["id"])                
                self.model.save()
                self.scene().parent_window.reload_scene()
        elif action == delete_action:
            confirm = QtWidgets.QMessageBox.question(None, "Eliminar", f"Eliminar {self.person.get('nombre')}?", QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if confirm == QtWidgets.QMessageBox.StandardButton.Yes:
                self.model.delete_person(self.person["id"])
                self.scene().parent_window.reload_scene()


# ------------------
# Dialogs
# ------------------

class EditPersonDialog(QtWidgets.QDialog):
    def __init__(self, person: Dict, model: FamilyModel, parent=None):
        super().__init__(parent)
        self.person = person
        self.model = model
        self.setWindowTitle(f"Editar: {person.get('nombre')}")
        self.build_ui()

    def build_ui(self):
        layout = QtWidgets.QFormLayout(self)
        self.name_ed = QtWidgets.QLineEdit(self.person.get("nombre", ""))
        self.dob_ed = QtWidgets.QLineEdit(self.person.get("fecha_nacimiento", ""))
        self.desc_ed = QtWidgets.QPlainTextEdit(self.person.get("descripcion", ""))

        # parents and children selectors
        people = [p for p in self.model.people if p["id"] != self.person["id"]]
        self.parents_list = QtWidgets.QListWidget()
        self.parents_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        for p in people:
            item = QtWidgets.QListWidgetItem(f"{p['id']} - {p['nombre']}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, p["id"])
            if p["id"] in self.person.get("padres", []):
                item.setSelected(True)
            self.parents_list.addItem(item)

        self.children_list = QtWidgets.QListWidget()
        self.children_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        for p in people:
            item = QtWidgets.QListWidgetItem(f"{p['id']} - {p['nombre']}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, p["id"])
            if p["id"] in self.person.get("hijos", []):
                item.setSelected(True)
            self.children_list.addItem(item)

        layout.addRow("Nombre:", self.name_ed)
        layout.addRow("Fecha de nacimiento:", self.dob_ed)
        layout.addRow("Descripción:", self.desc_ed)
        layout.addRow("Padres:", self.parents_list)
        layout.addRow("Hijos:", self.children_list)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def accept(self):
        name = self.name_ed.text().strip()
        dob = self.dob_ed.text().strip()
        desc = self.desc_ed.toPlainText().strip()
        parents = [it.data(QtCore.Qt.ItemDataRole.UserRole) for it in self.parents_list.selectedItems()]
        children = [it.data(QtCore.Qt.ItemDataRole.UserRole) for it in self.children_list.selectedItems()]
        self.model.update_person(self.person["id"], nombre=name, fecha_nacimiento=dob, descripcion=desc, padres=parents, hijos=children)
        super().accept()


# ------------------
# Scene / View / Main
# ------------------

class FamilyScene(QtWidgets.QGraphicsScene):
    def __init__(self, parent_window: 'MainWindow'):
        super().__init__()
        self.parent_window = parent_window


class FamilyView(QtWidgets.QGraphicsView):
    def __init__(self, scene: FamilyScene):
        super().__init__(scene)
        self.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing)
        self._zoom = 0
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._panning = False
        self._pan_start = QtCore.QPoint()

    def wheelEvent(self, event: QtGui.QWheelEvent):
        # Zoom centered on cursor
        delta = event.angleDelta().y()
        factor = 1.001 ** delta
        self.scale(factor, factor)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.MiddleButton or (event.button() == QtCore.Qt.MouseButton.LeftButton and event.modifiers() == QtCore.Qt.KeyboardModifier.Key_Space):
            self._panning = True
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            self._pan_start = event.pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self._panning:
            delta = self._pan_start - event.pos()
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if self._panning and (event.button() == QtCore.Qt.MouseButton.MiddleButton or event.button() == QtCore.Qt.MouseButton.LeftButton):
            self._panning = False
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Árbol genealógico - editor interactivo")
        self.model = FamilyModel()
        self.scene = FamilyScene(self)
        self.view = FamilyView(self.scene)
        self.setCentralWidget(self.view)
        self.node_map: Dict[int, NodeItem] = {}
        self.edge_items: List[EdgeItem] = []
        self.build_ui()
        self.reload_scene()

    def build_ui(self):
        toolbar = self.addToolBar("main")
        btn_reload = QtGui.QAction("Recargar", self)
        btn_reload.triggered.connect(self.reload_scene)
        toolbar.addAction(btn_reload)

        btn_save = QtGui.QAction("Guardar posiciones", self)
        btn_save.triggered.connect(self.save_positions)
        toolbar.addAction(btn_save)

        btn_add = QtGui.QAction("Agregar persona", self)
        btn_add.triggered.connect(self.add_person_dialog)
        toolbar.addAction(btn_add)

        btn_layout = QtGui.QAction("Auto-layout", self)
        btn_layout.triggered.connect(self.auto_layout)
        toolbar.addAction(btn_layout)

    def clear_scene(self):
        self.scene.clear()
        self.node_map.clear()
        self.edge_items.clear()

    def reload_scene(self):
        self.model.load()
        self.clear_scene()
        # create nodes
        for p in self.model.people:
            node = NodeItem(p, self.model)
            node.setPos(p.get("x") or 0, p.get("y") or 0)
            self.scene.addItem(node)
            node.scene().parent_window = self
            self.node_map[p["id"]] = node
        # create edges (parent -> child)
        for p in self.model.people:
            src = self.node_map.get(p["id"]) 
            if not src:
                continue
            for child_id in p.get("hijos", []):
                dst = self.node_map.get(child_id)
                if dst:
                    edge = EdgeItem(src, dst)
                    src.add_edge(edge)
                    dst.add_edge(edge)
                    self.scene.addItem(edge)
                    self.edge_items.append(edge)
        self.scene.update()

    def add_person_dialog(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Agregar persona", "Nombre:")
        if not ok or not name:
            return
        dob, _ = QtWidgets.QInputDialog.getText(self, "Agregar persona", "Fecha de nacimiento (YYYY-MM-DD):")
        desc, _ = QtWidgets.QInputDialog.getMultiLineText(self, "Agregar persona", "Descripción:")
        new_id = self.model.add_person(name, dob, desc)
        self.reload_scene()
        # center view on new node
        node = self.node_map.get(new_id)
        if node:
            self.view.centerOn(node)

    def auto_layout(self):
        # Simple top-down layout by generation (roots first)
        people = self.model.people
        id_to_children = {p["id"]: list(p.get("hijos", [])) for p in people}
        id_to_parents = {p["id"]: list(p.get("padres", [])) for p in people}

        # roots = people with no parents
        roots = [p["id"] for p in people if not p.get("padres")]
        if not roots:
            # fallback: pick id 1 or all
            roots = [p["id"] for p in people]

        levels: Dict[int, List[int]] = {}
        visited = set()
        current = roots
        level = 0
        while current:
            levels[level] = current
            next_level = []
            for nid in current:
                visited.add(nid)
                for c in id_to_children.get(nid, []):
                    if c not in visited and c not in next_level:
                        next_level.append(c)
            current = next_level
            level += 1

        # assign positions
        y_gap = 200
        x_gap = 200
        for lvl, ids in levels.items():
            n = len(ids)
            for i, nid in enumerate(ids):
                x = (i - (n - 1) / 2) * x_gap
                y = lvl * y_gap
                node = self.node_map.get(nid)
                if node:
                    node.setPos(x, y)
        # update edges
        for e in self.edge_items:
            e.update_pos()

    def save_positions(self):
        # save x,y of each node into model and persist
        for id_, node in self.node_map.items():
            pos = node.pos()
            person = self.model.get(id_)
            if person is not None:
                person["x"] = pos.x()
                person["y"] = pos.y()
        self.model.save()
        QtWidgets.QMessageBox.information(self, "Guardado", "Posiciones guardadas en el JSON.")


# ------------------
# Entrypoint
# ------------------

def ensure_sample_data():
    # Create sample minimal data if none exists
    if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
        sample = [
            {"id": 1, "nombre": "Juan Pérez", "fecha_nacimiento": "1950-05-10", "padres": [], "hijos": [2], "descripcion": "Le gustaba pescar.", "x": -100, "y": 0},
            {"id": 2, "nombre": "María Pérez", "fecha_nacimiento": "1980-02-15", "padres": [1], "hijos": [3], "descripcion": "Aficionada a la pintura.", "x": 0, "y": 200},
            {"id": 3, "nombre": "Pedro Pérez", "fecha_nacimiento": "2010-08-12", "padres": [2], "hijos": [], "descripcion": "Le encanta dibujar.", "x": 100, "y": 400},
        ]
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False, indent=4)


def main():
    import sys
    ensure_sample_data()
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
