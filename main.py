import json
import math
import os
import random
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple

from PyQt6.QtCore import QElapsedTimer, QTimer, Qt, QUrl
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QKeyEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget
try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:
    QAudioOutput = None
    QMediaPlayer = None


Vec2 = Tuple[float, float]


@dataclass
class Beat:
    angle: float
    event: str


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    r: int
    g: int
    b: int


@dataclass
class PerfectRing:
    x: float
    y: float
    life: float
    max_life: float


@dataclass
class PerfectLabel:
    x: float
    y: float
    life: float
    max_life: float


def rotate_screen(vec: Vec2, deg: float) -> Vec2:
    """Rotate vector in screen coordinates (y-axis points down)."""
    rad = math.radians(deg)
    x, y = vec
    return (x * math.cos(rad) + y * math.sin(rad), -x * math.sin(rad) + y * math.cos(rad))


def vec_add(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] + b[0], a[1] + b[1])


def vec_sub(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] - b[0], a[1] - b[1])


def vec_len(v: Vec2) -> float:
    return math.hypot(v[0], v[1])


def vec_scale(v: Vec2, k: float) -> Vec2:
    return (v[0] * k, v[1] * k)


def vec_norm(v: Vec2) -> Vec2:
    length = vec_len(v)
    if length == 0:
        return (1.0, 0.0)
    return (v[0] / length, v[1] / length)


class FireAndIceGame(QWidget):
    LINE_LENGTH = 120.0
    BALL_RADIUS = 12
    NODE_RADIUS = 5
    PRESTART_TURNS = 3
    CLOCKWISE = -1
    COUNTER_CLOCKWISE = 1
    CAMERA_PIXELS_PER_UNIT = 2.0
    CAMERA_SMOOTH = 3.2
    BACKGROUND_OPACITY = 0.42

    def __init__(self, level_path: str, mode: str = "default") -> None:
        super().__init__()
        self.level_path = level_path
        self.level_name = ""
        self.mode = mode if mode in {"default", "auto", "hard"} else "default"

        self.beats: List[Beat] = []
        self.bpm = 120.0
        self.nodes: List[Vec2] = []
        self.beat_dirs: List[int] = []

        self.state = "prestart"  # prestart, playing, failed, won
        self.fail_reason = ""
        self.elapsed = QElapsedTimer()

        self.prestart_angle = 0.0
        self.current_beat_idx = 0
        self.current_angle = 0.0
        self.carry_offset = 0.0
        self.player_hit_this_beat = False
        self.perfect_hits = 0
        self.good_hits = 0
        self.particles: List[Particle] = []
        self.perfect_rings: List[PerfectRing] = []
        self.perfect_labels: List[PerfectLabel] = []

        self.ball_a_pos: Vec2 = (0.0, 0.0)
        self.ball_b_pos: Vec2 = (0.0, 0.0)
        self.camera_pos: Vec2 = (0.0, 0.0)
        self.audio_player = None
        self.audio_output = None
        self.audio_path = ""
        self.background_image = QPixmap()

        self.setWindowTitle("Fire and Ice")
        self.resize(1200, 800)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Ensure close() destroys the window so hidden game loops do not accumulate.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.load_level()
        self.load_background()
        self.build_map()
        self.init_audio()
        self.reset_run()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.elapsed.start()

    def shutdown(self) -> None:
        if hasattr(self, "timer") and self.timer.isActive():
            self.timer.stop()
        self.stop_level_music()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    @property
    def angular_speed(self) -> float:
        # BPM means how many 180-degree turns happen per minute.
        return self.bpm * 180.0 / 60.0

    @property
    def success_tolerance(self) -> float:
        return 30.0

    @property
    def fail_tolerance(self) -> float:
        return 30.0 if self.mode == "hard" else 60.0

    def load_level(self) -> None:
        with open(self.level_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.level_name = data.get("levelname", os.path.basename(self.level_path))
        self.bpm = float(data["initial_bpm"])
        self.beats = [Beat(float(b["angle"]), str(b.get("event", "none"))) for b in data["Beats"]]
        if not self.beats:
            raise ValueError("关卡没有任何节拍数据。")

    def find_matching_background(self) -> QPixmap:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        bkg_dir = os.path.join(base_dir, "bkgimage")
        if not os.path.isdir(bkg_dir):
            return QPixmap()

        level_stem = os.path.splitext(os.path.basename(self.level_path))[0]
        names = []
        for name in (self.level_name, level_stem):
            if name and name not in names:
                names.append(name)

        extensions = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
        for name in names:
            for ext in extensions:
                path = os.path.join(bkg_dir, f"{name}{ext}")
                if os.path.exists(path):
                    pixmap = QPixmap(path)
                    if not pixmap.isNull():
                        return pixmap

            target = name.lower()
            for file_name in os.listdir(bkg_dir):
                stem, ext = os.path.splitext(file_name)
                if stem.lower() == target and ext.lower() in extensions:
                    pixmap = QPixmap(os.path.join(bkg_dir, file_name))
                    if not pixmap.isNull():
                        return pixmap
        return QPixmap()

    def load_background(self) -> None:
        self.background_image = self.find_matching_background()

    def find_matching_audio(self) -> str:
        level_stem = os.path.splitext(os.path.basename(self.level_path))[0]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        audio_dir = os.path.join(base_dir, "audio")
        if not os.path.isdir(audio_dir):
            return ""

        expected = os.path.join(audio_dir, f"{level_stem}.mp3")
        if os.path.exists(expected):
            return expected

        target_name = f"{level_stem}.mp3".lower()
        for name in os.listdir(audio_dir):
            if name.lower() == target_name:
                return os.path.join(audio_dir, name)
        return ""

    def init_audio(self) -> None:
        self.audio_path = self.find_matching_audio()
        if not self.audio_path or QMediaPlayer is None or QAudioOutput is None:
            return
        self.audio_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.65)
        self.audio_player.setAudioOutput(self.audio_output)

    def stop_level_music(self) -> None:
        if self.audio_player is not None:
            self.audio_player.stop()

    def play_level_music(self) -> None:
        if self.audio_player is None or not self.audio_path:
            return
        self.audio_player.stop()
        self.audio_player.setSource(QUrl.fromLocalFile(self.audio_path))
        self.audio_player.play()

    def build_map(self) -> None:
        self.nodes = [(0.0, 0.0), (self.LINE_LENGTH, 0.0)]
        self.beat_dirs = []
        direction = self.CLOCKWISE

        for beat in self.beats:
            if beat.event == "reverse":
                direction *= -1
            self.beat_dirs.append(direction)

            center = self.nodes[-1]
            prev_node = self.nodes[-2]
            in_vec = vec_sub(prev_node, center)
            out_vec = rotate_screen(in_vec, direction * beat.angle)
            out_vec = vec_scale(vec_norm(out_vec), self.LINE_LENGTH)
            next_node = vec_add(center, out_vec)
            self.nodes.append(next_node)

    def reset_run(self) -> None:
        self.state = "prestart"
        self.fail_reason = ""
        self.prestart_angle = 0.0
        self.current_beat_idx = 0
        self.current_angle = 0.0
        self.carry_offset = 0.0
        self.player_hit_this_beat = False
        self.perfect_hits = 0
        self.good_hits = 0
        self.particles.clear()
        self.perfect_rings.clear()
        self.perfect_labels.clear()
        self.ball_a_pos = self.nodes[0]
        self.ball_b_pos = self.nodes[1]
        self.camera_pos = self.nodes[0]
        self.stop_level_music()

    def tick(self) -> None:
        dt = self.elapsed.restart() / 1000.0
        if self.state == "prestart":
            self.update_prestart(dt)
        elif self.state == "playing":
            self.update_playing(dt)
        self.update_camera(dt)
        self.update_particles(dt)
        self.update()

    def update_prestart(self, dt: float) -> None:
        # Ball B rotates clockwise around node 0 for 3 full circles at 2x speed.
        self.prestart_angle -= self.angular_speed * 2.0 * dt
        center = self.nodes[0]
        start_vec = vec_sub(self.nodes[1], self.nodes[0])
        rot_vec = rotate_screen(start_vec, self.prestart_angle)
        self.ball_a_pos = self.nodes[0]
        self.ball_b_pos = vec_add(center, rot_vec)

        if self.prestart_angle <= -self.PRESTART_TURNS * 360.0:
            self.state = "playing"
            self.current_beat_idx = 0
            self.current_angle = self.carry_offset
            self.player_hit_this_beat = False
            self.sync_ball_positions()
            self.play_level_music()

    def sync_ball_positions(self) -> None:
        if self.current_beat_idx >= len(self.beats):
            return

        center_idx = self.current_beat_idx + 1
        prev_idx = self.current_beat_idx
        center = self.nodes[center_idx]
        prev_node = self.nodes[prev_idx]
        beat_dir = self.beat_dirs[self.current_beat_idx]

        start_vec = vec_sub(prev_node, center)
        cur_vec = rotate_screen(start_vec, beat_dir * self.current_angle)
        moving_pos = vec_add(center, cur_vec)

        # Even beat: fixed ball is B at center, moving ball is A.
        if self.current_beat_idx % 2 == 0:
            self.ball_b_pos = center
            self.ball_a_pos = moving_pos
        else:
            self.ball_a_pos = center
            self.ball_b_pos = moving_pos

    def update_playing(self, dt: float) -> None:
        if self.current_beat_idx >= len(self.beats):
            self.state = "won"
            return

        beat = self.beats[self.current_beat_idx]
        if self.mode != "auto" and self.audio_player is not None and self.audio_player.position() == 0:
            return
        self.current_angle += self.angular_speed * dt
        self.sync_ball_positions()

        if self.current_angle >= beat.angle:
            if self.mode == "auto" or self.player_hit_this_beat:
                self.handle_beat_landing()
                return
            if self.current_angle - beat.angle > self.fail_tolerance:
                self.fail(f"未按键踩点（节点 {self.current_beat_idx + 1}）")

    def handle_beat_landing(self) -> None:
        beat = self.beats[self.current_beat_idx]

        if self.mode != "auto" and not self.player_hit_this_beat:
            self.fail(f"未按键踩点（节点 {self.current_beat_idx + 1}）")
            return

        # Snap to exact node after landing.
        self.current_angle = beat.angle
        self.sync_ball_positions()

        if beat.event == "complete":
            self.state = "won"
            self.stop_level_music()
            return

        self.current_beat_idx += 1
        self.current_angle = self.carry_offset
        self.carry_offset = 0.0
        self.player_hit_this_beat = False
        self.sync_ball_positions()

    def fail(self, reason: str) -> None:
        self.state = "failed"
        self.fail_reason = reason
        self.stop_level_music()

    def handle_hit_input(self) -> None:
        if self.state != "playing" or self.mode == "auto":
            return
        if self.current_beat_idx >= len(self.beats):
            return

        target = self.beats[self.current_beat_idx].angle
        err = self.current_angle - target
        abs_err = abs(err)

        # In manual modes, any hit within fail_tolerance is accepted.
        if abs_err <= self.fail_tolerance:
            is_perfect = abs_err < self.success_tolerance
            if is_perfect:
                self.perfect_hits += 1
            elif abs_err <= 60.0:
                self.good_hits += 1
            self.player_hit_this_beat = True
            self.carry_offset = err
            self.current_angle = target
            self.sync_ball_positions()
            if is_perfect:
                self.spawn_perfect_effect(self.get_moving_ball_pos())
            self.handle_beat_landing()
            return

        self.fail(f"偏差过大：{abs_err:.1f}°（节点 {self.current_beat_idx + 1}）")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_M:
            self.mode = {"default": "auto", "auto": "hard", "hard": "default"}[self.mode]
            self.reset_run()
            return

        if self.state in {"failed", "won"}:
            self.reset_run()
            return

        if self.state == "playing":
            self.handle_hit_input()

    def get_camera_target(self) -> Vec2:
        if self.state == "prestart":
            return self.nodes[0]
        if self.state == "playing":
            # Follow the current pivot node instead of moving balls
            # to avoid beat-to-beat vertical oscillation.
            center_idx = min(self.current_beat_idx + 1, len(self.nodes) - 1)
            return self.nodes[center_idx]
        if self.state in {"failed", "won"} and self.current_beat_idx + 1 < len(self.nodes):
            return self.nodes[self.current_beat_idx + 1]
        return self.nodes[0]

    def update_camera(self, dt: float) -> None:
        target = self.get_camera_target()
        factor = min(1.0, dt * self.CAMERA_SMOOTH)
        self.camera_pos = (
            self.camera_pos[0] + (target[0] - self.camera_pos[0]) * factor,
            self.camera_pos[1] + (target[1] - self.camera_pos[1]) * factor,
        )

    def map_to_screen(self, point: Vec2) -> Vec2:
        scale = self.CAMERA_PIXELS_PER_UNIT
        sx = (point[0] - self.camera_pos[0]) * scale + self.width() / 2.0
        sy = (point[1] - self.camera_pos[1]) * scale + self.height() / 2.0
        return (sx, sy)

    def get_moving_ball_pos(self) -> Vec2:
        if self.current_beat_idx % 2 == 0:
            return self.ball_a_pos
        return self.ball_b_pos

    def spawn_perfect_effect(self, world_pos: Vec2) -> None:
        sx, sy = self.map_to_screen(world_pos)
        ring_life = 0.7
        label_life = 0.85
        self.perfect_rings.append(PerfectRing(sx, sy, ring_life, ring_life))
        self.perfect_labels.append(PerfectLabel(sx, sy - 34.0, label_life, label_life))

        colors = (
            (255, 228, 96),
            (255, 255, 255),
            (255, 110, 90),
            (90, 190, 255),
            (255, 180, 60),
        )
        for _ in range(56):
            angle = random.uniform(0.0, math.tau)
            speed = random.uniform(220.0, 620.0)
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed
            life = random.uniform(0.55, 0.95)
            size = random.uniform(5.0, 13.0)
            r, g, b = colors[random.randrange(len(colors))]
            self.particles.append(
                Particle(
                    x=sx,
                    y=sy,
                    vx=vx,
                    vy=vy,
                    life=life,
                    max_life=life,
                    size=size,
                    r=r,
                    g=g,
                    b=b,
                )
            )
        self.update()

    def update_particles(self, dt: float) -> None:
        dt = min(dt, 0.033)

        alive_particles: List[Particle] = []
        drag = 0.9
        gravity = 120.0
        for particle in self.particles:
            particle.life -= dt
            if particle.life <= 0.0:
                continue
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.vy += gravity * dt
            particle.vx *= drag
            particle.vy *= drag
            alive_particles.append(particle)
        self.particles = alive_particles

        alive_rings: List[PerfectRing] = []
        for ring in self.perfect_rings:
            ring.life -= dt
            if ring.life > 0.0:
                alive_rings.append(ring)
        self.perfect_rings = alive_rings

        alive_labels: List[PerfectLabel] = []
        for label in self.perfect_labels:
            label.life -= dt
            if label.life > 0.0:
                alive_labels.append(label)
        self.perfect_labels = alive_labels

    def draw_particles(self, painter: QPainter) -> None:
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        for ring in self.perfect_rings:
            t = ring.life / ring.max_life
            radius = 16.0 + (1.0 - t) * 72.0
            alpha = int(220 * t)
            pen = QPen(QColor(255, 230, 110, alpha), 4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(ring.x - radius), int(ring.y - radius), int(radius * 2), int(radius * 2))

        painter.setPen(Qt.PenStyle.NoPen)
        for particle in self.particles:
            t = max(0.0, particle.life / particle.max_life)
            alpha = int(255 * t)
            size = particle.size * (0.5 + 0.5 * t)
            painter.setBrush(QColor(particle.r, particle.g, particle.b, alpha))
            painter.drawEllipse(int(particle.x - size), int(particle.y - size), int(size * 2), int(size * 2))

        families = QFontDatabase.families()
        mono_family = next((name for name in ("Menlo", "SF Mono", "Monaco", "Courier New", "Consolas") if name in families), "")
        for label in self.perfect_labels:
            t = max(0.0, label.life / label.max_life)
            alpha = int(255 * t)
            scale = 18 + int((1.0 - t) * 10)
            font = QFont(mono_family, scale) if mono_family else QFont()
            if not mono_family:
                font.setPointSize(scale)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(255, 244, 168, alpha))
            text = "PERFECT"
            text_width = painter.fontMetrics().horizontalAdvance(text)
            painter.drawText(int(label.x - text_width / 2), int(label.y), text)

        painter.restore()

    def draw_ball(self, painter: QPainter, pos: Vec2, color: QColor) -> None:
        sx, sy = self.map_to_screen(pos)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(int(sx - self.BALL_RADIUS), int(sy - self.BALL_RADIUS), self.BALL_RADIUS * 2, self.BALL_RADIUS * 2)

    def draw_background(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor(16, 16, 20))
        if self.background_image.isNull():
            return

        scaled = self.background_image.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.save()
        painter.setOpacity(self.BACKGROUND_OPACITY)
        painter.drawPixmap(x, y, scaled)
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.draw_background(painter)

        # Draw lines
        pen_line = QPen(QColor(80, 160, 255), 3)
        painter.setPen(pen_line)
        for i in range(len(self.nodes) - 1):
            a = self.map_to_screen(self.nodes[i])
            b = self.map_to_screen(self.nodes[i + 1])
            painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))

        # Draw nodes
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(240, 240, 245))
        for n in self.nodes:
            sx, sy = self.map_to_screen(n)
            painter.drawEllipse(int(sx - self.NODE_RADIUS), int(sy - self.NODE_RADIUS), self.NODE_RADIUS * 2, self.NODE_RADIUS * 2)

        # Draw balls
        self.draw_ball(painter, self.ball_a_pos, QColor(255, 94, 94))
        self.draw_ball(painter, self.ball_b_pos, QColor(88, 186, 255))

        # HUD
        painter.setPen(QColor(240, 240, 245))
        # Consolas is often missing on macOS; prefer available monospaced families.
        families = QFontDatabase.families()
        mono_family = next((name for name in ("Menlo", "SF Mono", "Monaco", "Courier New", "Consolas") if name in families), "")
        font = QFont(mono_family, 11) if mono_family else QFont()
        painter.setFont(font)

        status = f"Level: {self.level_name} | BPM: {self.bpm:.1f} | Mode: {self.mode}"
        painter.drawText(16, 28, status)

        if self.state == "prestart":
            info = "预备阶段：小球B正在3拍热身旋转..."
        elif self.state == "playing":
            info = f"进行中：第 {self.current_beat_idx + 1}/{len(self.beats)} 拍 | 按任意键踩点（M切模式）"
        elif self.state == "failed":
            info = f"失败：{self.fail_reason} | 按任意键重开（M切模式）"
        else:
            info = "胜利！按任意键重开（M切模式）"
            if self.mode == "default":
                total_beats = len(self.beats)
                acc = (self.perfect_hits / total_beats) if total_beats else 0.0
                info += f" | ACC: {acc * 100:.2f}%"
        painter.drawText(16, 52, info)

        self.draw_particles(painter)

        if self.state == "won":
            if self.mode == "default":
                total_beats = len(self.beats)
                acc = (self.perfect_hits / total_beats) if total_beats else 0.0
                center_text = f"恭喜通关！准确率：{acc * 100:.2f}%"
            elif self.mode == "hard":
                center_text = "严格模式通关！\n孩子你无敌了！"
            else:
                center_text = ""

            if center_text:
                painter.setPen(QColor(255, 244, 168))
                center_font = QFont(mono_family, 30) if mono_family else QFont()
                if not mono_family:
                    center_font.setPointSize(30)
                center_font.setBold(True)
                painter.setFont(center_font)
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, center_text)


class LevelSelectWindow(QWidget):
    def __init__(self, work_dir: str, mode: str = "default") -> None:
        super().__init__()
        self.work_dir = work_dir
        self.default_mode = mode if mode in {"default", "auto", "hard"} else "default"
        self.level_map: Dict[str, str] = {}
        self.game_window = None
        self.pending_level_name = ""
        self.pending_level_path = ""
        self.in_mode_select = False

        self.setWindowTitle("Fire and Ice - 选关")
        self.resize(720, 520)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.title_label = QLabel("选择关卡（仅显示同时存在 .json 与 .mp3 的关卡）")
        self.title_label.setStyleSheet("font-size: 18px; color: #f0f0f5;")

        self.level_list = QListWidget()
        self.level_list.itemSelectionChanged.connect(self.on_level_selection_changed)
        self.level_list.itemDoubleClicked.connect(self.on_level_item_double_clicked)
        self.level_list.setStyleSheet(
            """
            QListWidget {
                background: #18181e;
                color: #f0f0f5;
                border: 1px solid #3a3f58;
                font-size: 15px;
                padding: 6px;
            }
            QListWidget::item {
                padding: 8px 6px;
            }
            QListWidget::item:selected {
                background: #3d4d8a;
            }
            """
        )

        self.hint_label = QLabel("点击关卡名后进入模式选择。")
        self.hint_label.setStyleSheet("color: #a5abc7;")

        self.mode_title_label = QLabel("")
        self.mode_title_label.setStyleSheet("font-size: 17px; color: #f0f0f5;")

        self.normal_button = QPushButton("normal")
        self.normal_button.clicked.connect(lambda: self.start_pending_level("default"))
        self.auto_button = QPushButton("auto")
        self.auto_button.clicked.connect(lambda: self.start_pending_level("auto"))
        self.hard_button = QPushButton("hard")
        self.hard_button.clicked.connect(lambda: self.start_pending_level("hard"))
        self.back_button = QPushButton("返回选关")
        self.back_button.clicked.connect(self.show_level_list_page)

        for btn in (self.normal_button, self.auto_button, self.hard_button, self.back_button):
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #2e3d78;
                    color: #f0f0f5;
                    border: 1px solid #5a6bb2;
                    border-radius: 6px;
                    padding: 10px;
                    font-size: 15px;
                }
                QPushButton:hover {
                    background-color: #3b4f99;
                }
                QPushButton:pressed {
                    background-color: #243364;
                }
                """
            )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(self.title_label)
        layout.addWidget(self.level_list)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.mode_title_label)
        layout.addWidget(self.normal_button)
        layout.addWidget(self.auto_button)
        layout.addWidget(self.hard_button)
        layout.addWidget(self.back_button)

        self.setStyleSheet("background-color: #101015;")
        self.refresh_levels()
        self.show_level_list_page()

    def refresh_levels(self) -> None:
        self.level_map = self.discover_playable_levels(self.work_dir)
        self.level_list.clear()
        for level_name in sorted(self.level_map.keys()):
            self.level_list.addItem(level_name)

        if self.level_list.count() > 0:
            self.level_list.setCurrentRow(0)
            self.hint_label.setText("点击关卡名后进入模式选择。")
        else:
            self.hint_label.setText("未找到可用关卡：需在 levels/ 与 audio/ 中同时存在同名文件。")

    @staticmethod
    def discover_playable_levels(work_dir: str) -> Dict[str, str]:
        levels_dir = os.path.join(work_dir, "levels")
        audio_dir = os.path.join(work_dir, "audio")
        if not os.path.isdir(levels_dir) or not os.path.isdir(audio_dir):
            return {}

        level_files = [f for f in os.listdir(levels_dir) if f.lower().endswith(".json")]
        audio_files = [f for f in os.listdir(audio_dir) if f.lower().endswith(".mp3")]
        level_stems = {os.path.splitext(name)[0]: os.path.join(levels_dir, name) for name in level_files}
        audio_stems = {os.path.splitext(name)[0] for name in audio_files}

        result: Dict[str, str] = {}
        for stem, path in level_stems.items():
            if stem in audio_stems:
                result[stem] = path
        return result

    def show_level_list_page(self) -> None:
        self.in_mode_select = False
        self.pending_level_name = ""
        self.pending_level_path = ""
        self.level_list.setVisible(True)
        self.hint_label.setVisible(True)
        self.mode_title_label.setVisible(False)
        self.normal_button.setVisible(False)
        self.auto_button.setVisible(False)
        self.hard_button.setVisible(False)
        self.back_button.setVisible(False)

    def show_mode_select_page(self, level_name: str, level_path: str) -> None:
        self.in_mode_select = True
        self.pending_level_name = level_name
        self.pending_level_path = level_path
        self.level_list.setVisible(False)
        self.hint_label.setVisible(False)
        self.mode_title_label.setVisible(True)
        self.normal_button.setVisible(True)
        self.auto_button.setVisible(True)
        self.hard_button.setVisible(True)
        self.back_button.setVisible(True)
        self.mode_title_label.setText(f"关卡：{level_name}\n请选择模式")

    def start_level_by_path(self, level_path: str, mode: str) -> None:
        if self.game_window is not None:
            self.game_window.shutdown()
            self.game_window.close()
            self.game_window = None

        self.game_window = FireAndIceGame(level_path=level_path, mode=mode)
        self.game_window.destroyed.connect(self.on_game_closed)
        self.hide()
        self.game_window.show()
        self.game_window.activateWindow()

    def on_level_selection_changed(self) -> None:
        item = self.level_list.currentItem()
        if item is None:
            return
        self.on_level_item_chosen(item.text())

    def on_level_item_double_clicked(self, item) -> None:
        self.on_level_item_chosen(item.text())

    def on_level_item_chosen(self, level_name: str) -> None:
        level_path = self.level_map.get(level_name, "")
        if not level_path:
            return
        self.show_mode_select_page(level_name, level_path)

    def start_pending_level(self, mode: str) -> None:
        if not self.pending_level_path:
            return
        self.start_level_by_path(self.pending_level_path, mode)

    def on_game_closed(self) -> None:
        if self.isVisible():
            return
        self.game_window = None
        self.refresh_levels()
        self.show_level_list_page()
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        super().keyPressEvent(event)


def parse_args(argv: List[str], work_dir: str) -> Tuple[str, str]:
    level_path = ""
    mode = "default"

    for arg in argv[1:]:
        lower = arg.lower()
        if lower in {"default", "auto", "hard"}:
            mode = lower
        elif arg.endswith(".json"):
            level_path = arg

    if level_path and not os.path.isabs(level_path):
        level_path = os.path.abspath(os.path.join(work_dir, level_path))

    return level_path, mode


def main() -> None:
    work_dir = os.path.dirname(os.path.abspath(__file__))
    level_path, mode = parse_args(sys.argv, work_dir)

    app = QApplication(sys.argv)
    select_window = LevelSelectWindow(work_dir=work_dir, mode=mode)
    select_window.show()
    if level_path:
        select_window.start_level_by_path(level_path, mode)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
