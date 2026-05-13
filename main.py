import json
import math
import os
import sys
from dataclasses import dataclass
from typing import List, Tuple

from PyQt6.QtCore import QElapsedTimer, QTimer, Qt, QUrl
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget
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

        self.ball_a_pos: Vec2 = (0.0, 0.0)
        self.ball_b_pos: Vec2 = (0.0, 0.0)
        self.camera_pos: Vec2 = (0.0, 0.0)
        self.audio_player = None
        self.audio_output = None
        self.audio_path = ""

        self.setWindowTitle("Fire and Ice")
        self.resize(1200, 800)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.load_level()
        self.build_map()
        self.init_audio()
        self.reset_run()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.elapsed.start()

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
        self.update()

    def update_prestart(self, dt: float) -> None:
        # Ball B rotates clockwise around node 0 for 3 full circles at 2x speed.
        self.prestart_angle += self.angular_speed * 2.0 * dt
        center = self.nodes[0]
        start_vec = vec_sub(self.nodes[1], self.nodes[0])
        rot_vec = rotate_screen(start_vec, self.prestart_angle)
        self.ball_a_pos = self.nodes[0]
        self.ball_b_pos = vec_add(center, rot_vec)

        if self.prestart_angle >= self.PRESTART_TURNS * 360.0:
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
        self.current_angle += self.angular_speed * dt
        self.sync_ball_positions()

        if self.current_angle >= beat.angle:
            self.handle_beat_landing()

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

        if abs_err <= self.success_tolerance:
            self.player_hit_this_beat = True
            self.carry_offset = err
            self.current_angle = target
            self.sync_ball_positions()
            self.handle_beat_landing()
            return

        if abs_err >= self.fail_tolerance:
            self.fail(f"偏差过大：{abs_err:.1f}°（节点 {self.current_beat_idx + 1}）")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return

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

    def draw_ball(self, painter: QPainter, pos: Vec2, color: QColor) -> None:
        sx, sy = self.map_to_screen(pos)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(int(sx - self.BALL_RADIUS), int(sy - self.BALL_RADIUS), self.BALL_RADIUS * 2, self.BALL_RADIUS * 2)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(16, 16, 20))

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
        font = QFont("Consolas", 11)
        painter.setFont(font)

        status = f"Level: {self.level_name} | BPM: {self.bpm:.1f} | Mode: {self.mode}"
        painter.drawText(16, 28, status)

        if self.state == "prestart":
            info = "预备阶段：小球B正在3拍热身旋转..."
        elif self.state == "playing":
            info = f"进行中：第 {self.current_beat_idx + 1}/{len(self.beats)} 拍 | 按任意键踩点（Esc退出，M切模式）"
        elif self.state == "failed":
            info = f"失败：{self.fail_reason} | 按任意键重开（Esc退出，M切模式）"
        else:
            info = "胜利！按任意键重开（Esc退出，M切模式）"
        painter.drawText(16, 52, info)


def pick_default_level(work_dir: str) -> str:
    levels_dir = os.path.join(work_dir, "levels")
    if not os.path.isdir(levels_dir):
        raise FileNotFoundError("未找到 levels 目录。")

    files = [f for f in os.listdir(levels_dir) if f.lower().endswith(".json")]
    if not files:
        raise FileNotFoundError("levels 目录中没有 json 关卡文件。")

    files.sort()
    preferred = os.path.join(levels_dir, "test1X.json")
    if os.path.exists(preferred):
        return preferred
    return os.path.join(levels_dir, files[0])


def parse_args(argv: List[str], work_dir: str) -> Tuple[str, str]:
    level_path = ""
    mode = "default"

    for arg in argv[1:]:
        lower = arg.lower()
        if lower in {"default", "auto", "hard"}:
            mode = lower
        elif arg.endswith(".json"):
            level_path = arg

    if not level_path:
        level_path = pick_default_level(work_dir)
    elif not os.path.isabs(level_path):
        level_path = os.path.abspath(os.path.join(work_dir, level_path))

    return level_path, mode


def main() -> None:
    work_dir = os.path.dirname(os.path.abspath(__file__))
    level_path, mode = parse_args(sys.argv, work_dir)

    app = QApplication(sys.argv)
    game = FireAndIceGame(level_path=level_path, mode=mode)
    game.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
