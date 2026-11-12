"""拓扑图画布：路由器/交换机/防火墙图标 + 连线 + 型号标注 + 安全检查警告气泡。

绘制约定（参考华为拓扑图标风格，纯 QPainter 手绘，不依赖图片资源）：
- switch  = 圆角矩形 + 双向箭头对
- router  = 圆形 + 十字箭头（四面路由）
- firewall= 矩形 + 砖墙线
- unknown = 普通圆角矩形（灰）
节点下方两行标注：设备名（加粗）+ 型号（次要色）。
链路：实线=LLDP 高置信，虚线=MAC 推断；中点标接口名（空间不够就只画线）。

交互（都通过信号给 main_window，画布不碰业务）：
- 点节点 → device_clicked(key)：补全检查指令 / 高亮设备表
- 点红色警告气泡 → finding_clicked(key)：右侧面板显示修复建议
- 悬停节点 → QToolTip 显示型号/角色/检查摘要
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QToolTip

from gui.theme import Palette

NODE_W, NODE_H = 108, 58
BUBBLE_R = 11                 # 警告气泡半径
LEVEL_GAP_Y = 110             # 层与层的垂直间距
NODE_GAP_X = 40               # 同层节点的水平间距


class TopologyCanvas(QWidget):
    device_clicked = pyqtSignal(str)      # node key
    finding_clicked = pyqtSignal(str)     # node key（点了警告气泡）

    def __init__(self, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.palette_ref = palette
        self.setMouseTracking(True)
        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        self._pos: dict[str, tuple[float, float]] = {}    # key → 中心点
        self._findings: dict[str, dict] = {}              # key → {high, medium, ...}
        self._selected: str = ""
        self._generated = ""

    # ---------------------------------------------------------------- 数据
    def set_model(self, model: dict) -> None:
        self._nodes = model.get("nodes") or []
        self._edges = model.get("edges") or []
        self._generated = model.get("generated", "")
        self._findings = {}
        self._relayout()
        self.update()

    def set_findings(self, findings: dict) -> None:
        """compliance.scan_devices() 的 results 按 key 索引。"""
        self._findings = {r.get("key", ""): r for r in (findings or {}).get("results", [])
                          if r.get("key")}
        self.update()

    def clear_findings(self) -> None:
        self._findings = {}
        self.update()

    def selected_key(self) -> str:
        return self._selected

    def retint(self, palette: Palette) -> None:
        """主题切换：只换配色引用重画，控件与数据全部保留。"""
        self.palette_ref = palette
        self.update()

    # ---------------------------------------------------------------- 布局
    def _relayout(self) -> None:
        """按层级分层布点：level 0（根/核心）在最上；没有连线的孤立设备垫底一行。"""
        if not self._nodes:
            return
        connected = {e["a"] for e in self._edges} | {e["b"] for e in self._edges}
        by_level: dict[int, list[dict]] = {}
        for n in self._nodes:
            lvl = int(n.get("level", 99))
            if n["key"] not in connected:
                lvl = 98                      # 孤立设备统一垫底，别按 99 散在中间
            by_level.setdefault(lvl, []).append(n)

        self._pos = {}
        y = 60.0
        width_needed = 0
        for lvl in sorted(by_level):
            row = by_level[lvl]
            w = len(row) * NODE_W + max(0, len(row) - 1) * NODE_GAP_X
            width_needed = max(width_needed, w)
        width_needed = max(width_needed, 400)
        self.setMinimumWidth(width_needed + 60)

        for lvl in sorted(by_level):
            row = sorted(by_level[lvl], key=lambda n: n["name"])
            total = len(row) * NODE_W + max(0, len(row) - 1) * NODE_GAP_X
            x = max(30.0, (self.width() - total) / 2) if self.width() > total else 30.0
            for n in row:
                self._pos[n["key"]] = (x + NODE_W / 2, y + NODE_H / 2)
                x += NODE_W + NODE_GAP_X
            y += LEVEL_GAP_Y
        # 底部预留图例行的高度（画在 height()-16 处，别让最后一行节点盖住）
        self.setMinimumHeight(int(y) - LEVEL_GAP_Y + 60 + 34)

    def resizeEvent(self, event):  # noqa: N802
        # 画布宽度变化（滚动区 widgetResizable 拉伸/窗口缩放）后重新居中，
        # 否则所有行停在首次布局的偏移上，看起来「整图偏到一边」
        super().resizeEvent(event)
        if self._nodes:
            self._relayout()
            self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event):  # noqa: N802  Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette_ref
        if not self._nodes:
            p.setPen(QColor(pal.text_faint))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "暂无拓扑数据：点「刷新拓扑」从最近一次发现结果加载")
            return

        # 连线先画（压在节点下面）。接口名只在与选中节点相关的边上标——
        # 大拓扑全标会互相叠成一片（曾 16 条边全标导致标签压在节点上）；
        # 边少时全标，方便小拓扑直读。
        label_all = len(self._edges) <= 10
        for e in self._edges:
            a, b = self._pos.get(e["a"]), self._pos.get(e["b"])
            if not a or not b:
                continue
            dashed = e.get("evidence") != "lldp" or e.get("confidence") != "high"
            pen = QPen(QColor(pal.border_strong if not dashed else pal.text_faint),
                       2 if not dashed else 1,
                       Qt.PenStyle.SolidLine if not dashed else Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
            if (e.get("a_if") and e.get("b_if")
                    and (label_all or self._selected in (e["a"], e["b"]))):
                p.setPen(QColor(pal.text_faint))
                f = QFont()
                f.setPointSize(7)
                p.setFont(f)
                mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                p.drawText(QRectF(mx - 70, my - 16, 140, 14),
                           Qt.AlignmentFlag.AlignCenter,
                           f"{e['a_if']} ↔ {e['b_if']}")

        for n in self._nodes:
            self._draw_node(p, n)

        self._draw_legend(p)

    def _draw_legend(self, p: QPainter) -> None:
        """底部图例：图标形状 + 线型 + 红色气泡含义（新手不用猜）。"""
        pal = self.palette_ref
        h = self.height()
        y = h - 16
        p.setPen(QColor(pal.text_faint))
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        x = 24.0
        # 线型
        p.setPen(QPen(QColor(pal.border_strong), 2))
        p.drawLine(int(x), y, int(x + 26), y)
        p.setPen(QColor(pal.text_faint))
        p.drawText(QRectF(x + 30, y - 8, 96, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LLDP 确认链路")
        x += 132
        p.setPen(QPen(QColor(pal.text_faint), 1, Qt.PenStyle.DashLine))
        p.drawLine(int(x), y, int(x + 26), y)
        p.setPen(QColor(pal.text_faint))
        p.drawText(QRectF(x + 30, y - 8, 110, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "MAC 推断链路")
        x += 146
        p.setBrush(QBrush(QColor(pal.err)))
        p.setPen(QPen(QColor(pal.err)))
        p.drawEllipse(QRectF(x, y - 6, 12, 12))
        p.setPen(QColor(pal.text_faint))
        p.drawText(QRectF(x + 17, y - 8, 190, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "高危设备数（点气泡看修复建议）")

    def _draw_node(self, p: QPainter, n: dict) -> None:
        pal = self.palette_ref
        cx, cy = self._pos[n["key"]]
        x, y = cx - NODE_W / 2, cy - NODE_H / 2
        selected = n["key"] == self._selected
        kind = n.get("kind", "unknown")

        body = QColor(pal.panel)
        ring = QColor(pal.accent) if selected else QColor(pal.border_strong)
        if kind == "switch":
            p.setBrush(QBrush(body))
            p.setPen(QPen(ring, 2 if selected else 1.4))
            p.drawRoundedRect(QRectF(x, y, NODE_W, NODE_H), 8, 8)
            self._draw_double_arrows(p, x, y)
        elif kind == "router":
            p.setBrush(QBrush(body))
            p.setPen(QPen(ring, 2 if selected else 1.4))
            r = NODE_H / 2
            p.drawEllipse(QRectF(cx - r, y, NODE_H, NODE_H))
            self._draw_cross_arrows(p, cx, cy)
        elif kind == "firewall":
            p.setBrush(QBrush(body))
            p.setPen(QPen(ring, 2 if selected else 1.4))
            p.drawRect(QRectF(x, y, NODE_W, NODE_H))
            self._draw_bricks(p, x, y)
        else:
            p.setBrush(QBrush(body))
            p.setPen(QPen(ring, 2 if selected else 1))
            p.drawRoundedRect(QRectF(x, y, NODE_W, NODE_H), 6, 6)
            # 未识别设备：中间一个「?」，和有图标的设备区分开（避免大黑块感）
            fq = QFont()
            fq.setBold(True)
            fq.setPointSize(16)
            p.setFont(fq)
            p.setPen(QColor(pal.text_faint))
            p.drawText(QRectF(x, y, NODE_W, NODE_H),
                       Qt.AlignmentFlag.AlignCenter, "?")

        # 名字 + 型号
        f = QFont()
        f.setBold(True)
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QColor(pal.text))
        p.drawText(QRectF(x - 10, y + NODE_H + 2, NODE_W + 20, 16),
                   Qt.AlignmentFlag.AlignCenter, str(n.get("name", "")))
        f2 = QFont()
        f2.setPointSize(7)
        p.setFont(f2)
        p.setPen(QColor(pal.text_dim))
        p.drawText(QRectF(x - 14, y + NODE_H + 17, NODE_W + 28, 14),
                   Qt.AlignmentFlag.AlignCenter, str(n.get("model", "")))

        # 高危警告气泡（红底白字，节点右上角）
        fd = self._findings.get(n["key"])
        if fd and fd.get("high", 0) > 0:
            bx, by = x + NODE_W - 4, y + 4
            p.setBrush(QBrush(QColor(pal.err)))
            p.setPen(QPen(QColor(pal.err)))
            p.drawEllipse(QRectF(bx - BUBBLE_R, by - BUBBLE_R,
                                 BUBBLE_R * 2, BUBBLE_R * 2))
            f3 = QFont()
            f3.setBold(True)
            f3.setPointSize(8)
            p.setFont(f3)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(bx - BUBBLE_R, by - BUBBLE_R, BUBBLE_R * 2, BUBBLE_R * 2),
                       Qt.AlignmentFlag.AlignCenter, str(fd["high"]))

    def _draw_double_arrows(self, p: QPainter, x: float, y: float) -> None:
        pal = self.palette_ref
        p.setPen(QPen(QColor(pal.text_dim), 1.6))
        cy = y + NODE_H / 2
        x0, x1 = x + 16, x + NODE_W - 16
        p.drawLine(int(x0), int(cy - 5), int(x1), int(cy - 5))
        p.drawLine(int(x0), int(cy + 5), int(x1), int(cy + 5))
        for ex, dx in ((x1, -1), (x0, 1)):
            p.drawLine(int(ex), int(cy - 5), int(ex + dx * 6), int(cy - 5))
            p.drawLine(int(ex), int(cy + 5), int(ex + dx * 6), int(cy + 5))

    def _draw_cross_arrows(self, p: QPainter, cx: float, cy: float) -> None:
        """路由器：圆内十字双向箭头（经典画法，不画斜线避免米字感）。"""
        pal = self.palette_ref
        p.setPen(QPen(QColor(pal.text_dim), 1.6))
        r = NODE_H / 2 - 12
        cy = cy - 1
        for ax, ay, bx, by in ((-r, 0, r, 0), (0, -r, 0, r)):
            p.drawLine(int(cx + ax), int(cy + ay), int(cx + bx), int(cy + by))
        # 水平箭头两端
        for ex, dx in ((cx + r, -1), (cx - r, 1)):
            p.drawLine(int(ex), int(cy - 4), int(ex + dx * 5), int(cy))
            p.drawLine(int(ex), int(cy + 4), int(ex + dx * 5), int(cy))
        # 垂直箭头两端
        for ey, dy in ((cy - r, 1), (cy + r, -1)):
            p.drawLine(int(cx - 4), int(ey), int(cx), int(ey + dy * 5))
            p.drawLine(int(cx + 4), int(ey), int(cx), int(ey + dy * 5))

    def _draw_bricks(self, p: QPainter, x: float, y: float) -> None:
        pal = self.palette_ref
        p.setPen(QPen(QColor(pal.text_faint), 1))
        step = 14
        yy = y + 10
        i = 0
        while yy < y + NODE_H - 4:
            off = (step / 2) if i % 2 else 0
            xx = x + 8 - off
            while xx < x + NODE_W - 8:
                p.drawLine(int(max(x + 8, xx)), int(yy),
                           int(min(x + NODE_W - 8, xx + step - 4)), int(yy))
                xx += step
            yy += 8
            i += 1

    # ---------------------------------------------------------------- 命中
    def _hit_node(self, pos) -> dict | None:
        for n in self._nodes:
            cx, cy = self._pos.get(n["key"], (0, 0))
            if (abs(pos.x() - cx) <= NODE_W / 2 + 4
                    and abs(pos.y() - cy) <= NODE_H / 2 + 4):
                return n
        return None

    def _hit_bubble(self, pos) -> dict | None:
        for n in self._nodes:
            fd = self._findings.get(n["key"])
            if not fd or fd.get("high", 0) <= 0:
                continue
            cx, cy = self._pos.get(n["key"], (0, 0))
            bx, by = cx + NODE_W / 2 - 4, cy - NODE_H / 2 + 4
            if math.hypot(pos.x() - bx, pos.y() - by) <= BUBBLE_R + 3:
                return n
        return None

    def mousePressEvent(self, event):  # noqa: N802
        pos = event.position()
        hit = self._hit_bubble(pos)
        if hit is not None:
            self._selected = hit["key"]
            self.update()
            self.finding_clicked.emit(hit["key"])
            return
        node = self._hit_node(pos)
        if node is not None:
            self._selected = node["key"]
            self.update()
            self.device_clicked.emit(node["key"])
        else:
            if self._selected:
                self._selected = ""
                self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        node = self._hit_bubble(pos) or self._hit_node(pos)
        # 悬停可点的对象时换手型光标（拓扑是交互入口，可点击性要看得出来）
        self.setCursor(Qt.CursorShape.PointingHandCursor if node is not None
                       else Qt.CursorShape.ArrowCursor)
        if node is None:
            return
        fd = self._findings.get(node["key"])
        lines = [f"{node['name']}｜{node['model']}",
                 f"角色：{node.get('role', '—')}",
                 f"地址：{node['host']}:{node['port']}"]
        if fd:
            if fd.get("error"):
                lines.append(f"检查：{fd['error']}")
            else:
                lines.append(f"安全检查：高危 {fd.get('high', 0)} · "
                             f"中危 {fd.get('medium', 0)} · "
                             f"需人工 {fd.get('manual', 0)}")
        elif self._findings:
            lines.append("安全检查：未覆盖（未扫描或离线）")
        QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)
