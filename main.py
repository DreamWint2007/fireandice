import sys
import math
import json
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QTimer
import pygame

class Node:
    def __init__(self, x, y, angle, event="none"):
        self.x = x
        self.y = y
        self.angle = angle
        self.event = event

class ADOFAI(QWidget):
    def __init__(self, level_path, game_mode="normal"):
        super().__init__()
        self.level_path = level_path
        self.game_mode = game_mode  # normal, auto, hard
        if game_mode == "hard":
            self.hit_tolerance = 30.0
            self.miss_tolerance = 30.0
        else:
            self.hit_tolerance = 60.0
            self.miss_tolerance = 60.0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.init_game()
        
    def init_game(self):
        # Load level data
        with open(self.level_path, 'r', encoding='utf-8') as f:
            self.level_data = json.load(f)
            
        self.bpm = self.level_data.get('initial_bpm', 150.0)
        self.beats = self.level_data.get('Beats', [])
        
        # Audio setup
        pygame.mixer.init()
        audio_file = f"audio/{self.level_data.get('levelname', '')}.ogg"
        if not os.path.exists(audio_file):
            audio_file = f"audio/{self.level_data.get('levelname', '')}.mp3"
        if os.path.exists(audio_file):
             pygame.mixer.music.load(audio_file)
        
        self.nodes = []
        self.node_length = 50.0
        
        # Generate Nodes
        curr_x, curr_y = 0.0, 0.0
        self.nodes.append(Node(curr_x, curr_y, 0)) # Node 0
        curr_angle_deg = 0.0
        
        for beat in self.beats:
            beat_angle = beat.get("angle", 180)
            event = beat.get("event", "none")
            
            # ADOFAI mechanics: the angle is relative to the previous segment.
            curr_angle_deg += (180 - beat_angle)
            
            rad = math.radians(curr_angle_deg)
            curr_x += self.node_length * math.cos(rad)
            curr_y -= self.node_length * math.sin(rad)
            self.nodes.append(Node(curr_x, curr_y, beat_angle, event))

        self.reset_game_state()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_game)
        self.timer.start(16) # ~60fps

    def reset_game_state(self):
        self.state = "pre_start" # pre_start, playing, win, lose
        self.curr_node_idx = 0
        
        self.ball_A_fixed = True
        self.ball_fixed_idx = 0 
        self.ball_moving_idx = 1
        
        self.rotation_dir = 1 # 1 = clockwise, -1 = counter-clockwise
        
        # Calculate angular velocity
        # BPM is 180 degrees per minute
        # degrees per second: BPM * 180 / 60 = BPM * 3
        self.deg_per_sec = self.bpm * 3.0
        
        # Pre-start: Ball B rotates from node 1 with 2x speed for 3 full circles
        self.pre_start_circle_count = 0
        self.current_angle_deg = 0.0
        self.target_angle_deg = 180.0
        self.current_time = 0.0
        
        # Pre-start starts at node 1 (ball_moving_idx), ball A is fixed at node 0
        self.ball_fixed_pos = (self.nodes[0].x, self.nodes[0].y)
        dx = self.nodes[1].x - self.nodes[0].x
        dy = self.nodes[1].y - self.nodes[0].y
        self.base_angle = math.degrees(math.atan2(-dy, dx)) # Starting angle between 0 and 1
        
        self.current_angle_offset = 0.0

        self.camera_x = self.nodes[0].x
        self.camera_y = self.nodes[0].y
        
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()

    def update_game(self):
        dt = 16.0 / 1000.0  # seconds
        
        if self.state == "pre_start":
            speed = self.deg_per_sec * 2.0 * dt
            self.current_angle_offset += speed
            
            if self.current_angle_offset >= 360.0:
                self.current_angle_offset -= 360.0
                self.pre_start_circle_count += 1
                
                if self.pre_start_circle_count >= 3:
                    self.current_angle_offset = 0.0
                    self.start_playing()
                    
        elif self.state == "playing":
            # Update moving ball position
            prev_off = self.current_angle_offset
            speed = self.deg_per_sec * dt * self.rotation_dir
            self.current_angle_offset += speed
            new_off = self.current_angle_offset

            auto_advanced = False
            if self.game_mode == "auto":
                crossed_zero = (
                    self.rotation_dir == 1 and prev_off <= 0.0 and new_off >= 0.0
                ) or (
                    self.rotation_dir == -1 and prev_off >= 0.0 and new_off <= 0.0
                )
                if crossed_zero or abs(new_off) < 1e-6:
                    self.advance_node(0.0 if crossed_zero else new_off)
                    auto_advanced = True

            if not auto_advanced:
                if self.rotation_dir == 1 and self.current_angle_offset > self.miss_tolerance:
                    self.lose_game()
                elif self.rotation_dir == -1 and self.current_angle_offset < -self.miss_tolerance:
                    self.lose_game()
            
        # Update Camera
        fixed_node = self.nodes[self.curr_node_idx]
        self.camera_x += (fixed_node.x - self.camera_x) * 0.1
        self.camera_y += (fixed_node.y - self.camera_y) * 0.1
        
        self.update()

    def start_playing(self):
        self.state = "playing"
        if pygame.mixer.get_init():
             pygame.mixer.music.play()
        self.advance_node(0.0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.window().close()
            return
            
        if self.state in ["win", "lose"]:
            self.reset_game_state()
            return
            
        if self.state == "playing":
            if self.game_mode == "auto":
                return
            # Attempt to hit the node
            diff = self.current_angle_offset
            if abs(diff) <= self.hit_tolerance:
                self.advance_node(diff)
            else:
                self.lose_game()

    def advance_node(self, diff):
        self.curr_node_idx += 1
        if self.curr_node_idx >= len(self.nodes) - 1 or self.nodes[self.curr_node_idx].event == "complete":
            self.win_game()
            return
            
        # Swap balls
        self.ball_A_fixed = not self.ball_A_fixed
        
        # Check reverse event
        if self.nodes[self.curr_node_idx].event == "reverse":
            self.rotation_dir *= -1
            
        # Calculate base angle for the new fixed node (towards n+1)
        dx = self.nodes[self.curr_node_idx+1].x - self.nodes[self.curr_node_idx].x
        dy = self.nodes[self.curr_node_idx+1].y - self.nodes[self.curr_node_idx].y
        self.base_angle = math.degrees(math.atan2(-dy, dx))
        
        # New base angle is 0 offset perfectly. We start from n-1, which is at an angle 'beat_angle' 
        next_beat_angle = self.nodes[self.curr_node_idx].angle
        if self.rotation_dir == 1:
            self.current_angle_offset = -next_beat_angle + diff
        else:
            self.current_angle_offset = next_beat_angle + diff

    def lose_game(self):
        self.state = "lose"
        if pygame.mixer.get_init():
             pygame.mixer.music.stop()

    def win_game(self):
        self.state = "win"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Draw background
        painter.fillRect(0, 0, width, height, QColor(30, 30, 30))
        
        painter.translate(width / 2 - self.camera_x, height / 2 - self.camera_y)
        
        # Draw path
        pen = QPen(QColor(200, 200, 200), 5)
        painter.setPen(pen)
        for i in range(len(self.nodes) - 1):
            painter.drawLine(int(self.nodes[i].x), int(self.nodes[i].y), int(self.nodes[i+1].x), int(self.nodes[i+1].y))
            
        # Draw nodes
        for i, node in enumerate(self.nodes):
            if i < self.curr_node_idx:
                painter.setBrush(QColor(100, 100, 100))
            elif i == self.curr_node_idx:
                painter.setBrush(QColor(255, 255, 255))
            else:
                painter.setBrush(QColor(200, 200, 200))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(node.x) - 10, int(node.y) - 10, 20, 20)
            
        # Draw balls
        fixed_node = self.nodes[self.curr_node_idx]
        if self.curr_node_idx + 1 < len(self.nodes):
            next_node = self.nodes[self.curr_node_idx + 1]
            rad = math.radians(self.base_angle + self.current_angle_offset)
            moving_x = fixed_node.x + self.node_length * math.cos(rad)
            moving_y = fixed_node.y - self.node_length * math.sin(rad)
        else:
            moving_x, moving_y = fixed_node.x, fixed_node.y
            
        if self.ball_A_fixed:
            color_fixed = QColor(255, 50, 50)  # Red (Fire)
            color_moving = QColor(50, 200, 255) # Blue (Ice)
        else:
            color_fixed = QColor(50, 200, 255)
            color_moving = QColor(255, 50, 50)
            
        painter.setBrush(color_fixed)
        painter.drawEllipse(int(fixed_node.x) - 15, int(fixed_node.y) - 15, 30, 30)
        
        painter.setBrush(color_moving)
        painter.drawEllipse(int(moving_x) - 15, int(moving_y) - 15, 30, 30)
        
        # Reset transform for HUD
        painter.resetTransform()
        
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 24))
        mode_label = {"normal": "基础", "auto": "自动", "hard": "困难"}.get(
            self.game_mode, self.game_mode
        )
        painter.drawText(20, height - 20, f"模式: {mode_label}")
        if self.state == "pre_start":
            painter.drawText(20, 40, f"Ready... {3 - self.pre_start_circle_count}")
        elif self.state == "lose":
            painter.drawText(20, 40, "Game Over! Press any key to restart.")
        elif self.state == "win":
            painter.drawText(20, 40, "Level Complete! Press any key to restart.")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dance of Fire and Ice Clone")
        self.setGeometry(100, 100, 800, 600)

        level_file = "levels/test1X.json"
        game_mode = "normal"
        for arg in sys.argv[1:]:
            low = arg.lower()
            if low in ("auto", "hard", "normal"):
                game_mode = low
            elif os.path.isfile(arg) or arg.endswith(".json"):
                level_file = arg

        if not os.path.exists(level_file):
            print("Level file not found!")
            sys.exit()

        self.game = ADOFAI(level_file, game_mode=game_mode)
        self.setCentralWidget(self.game)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
