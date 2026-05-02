import sys
import os
import json
import random
import subprocess
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QFileDialog, QDoubleSpinBox, 
                             QHBoxLayout, QMessageBox)
from PyQt6.QtCore import Qt
import librosa
import numpy as np

class LevelGenerator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fire and Ice Level Generator")
        self.setGeometry(200, 200, 400, 300)
        
        self.audio_path = None
        self.generated_level_path = None
        
        self.init_ui()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        
        # Audio selection
        self.lbl_audio = QLabel("No audio selected")
        self.lbl_audio.setWordWrap(True)
        btn_select_audio = QPushButton("Select Audio File (/audio)")
        btn_select_audio.clicked.connect(self.select_audio)
        
        # Reverse Probability
        hbox_ratio = QHBoxLayout()
        lbl_ratio = QLabel("Reverse Event Ratio (%):")
        self.spin_ratio = QDoubleSpinBox()
        self.spin_ratio.setRange(0, 100)
        self.spin_ratio.setValue(0.0)
        self.spin_ratio.setSingleStep(5.0)
        hbox_ratio.addWidget(lbl_ratio)
        hbox_ratio.addWidget(self.spin_ratio)
        
        # Generate and Test buttons
        btn_generate = QPushButton("Generate Level")
        btn_generate.clicked.connect(self.generate_level)
        
        self.btn_test = QPushButton("Test Level")
        self.btn_test.clicked.connect(self.test_level)
        self.btn_test.setEnabled(False)
        
        self.lbl_status = QLabel("Ready")
        
        layout.addWidget(self.lbl_audio)
        layout.addWidget(btn_select_audio)
        layout.addLayout(hbox_ratio)
        layout.addWidget(btn_generate)
        layout.addWidget(self.btn_test)
        layout.addWidget(self.lbl_status)
        
        central_widget.setLayout(layout)
        
    def select_audio(self):
        # Default dir to /audio if it exists
        default_dir = os.path.join(os.getcwd(), "audio")
        if not os.path.exists(default_dir):
            os.makedirs(default_dir, exist_ok=True)
            
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio", default_dir, "Audio Files (*.wav *.mp3 *.ogg)"
        )
        if file_path:
            self.audio_path = file_path
            self.lbl_audio.setText(f"Selected: {os.path.basename(self.audio_path)}")
            self.lbl_status.setText("Ready to generate.")
            self.btn_test.setEnabled(False)

    def generate_level(self):
        if not self.audio_path:
            QMessageBox.warning(self, "Error", "Please select an audio file first!")
            return
            
        self.lbl_status.setText("Analyzing audio... (Please wait)")
        QApplication.processEvents() # Force UI update
        
        try:
            # Analyze audio using librosa
            y, sr = librosa.load(self.audio_path)
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)
            
            # Handle tempo array
            bpm = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
            time_per_180 = 60.0 / bpm
            
            diffs = np.diff(beat_times)
            
            beats = []
            accumulated_time = 0.0
            ratio_prob = self.spin_ratio.value() / 100.0
            
            for diff in diffs:
                accumulated_time += diff
                raw_angle = (accumulated_time / time_per_180) * 180.0
                
                # Quantize to 30 degrees
                quantized_angle = round(raw_angle / 30.0) * 30.0
                
                # Remove noise: if the angle is smaller than 30, keep accumulating
                if quantized_angle >= 30.0:
                    event = "none"
                    if random.random() < ratio_prob:
                        event = "reverse"
                    beats.append({
                        "angle": quantized_angle,
                        "event": event
                    })
                    accumulated_time = 0.0 # Reset after finding a valid beat
            
            # Set the last beat event to complete
            if len(beats) > 0:
                beats[-1]["event"] = "complete"
                
            level_name = os.path.splitext(os.path.basename(self.audio_path))[0]
            level_data = {
                "levelname": level_name,
                "initial_bpm": bpm,
                "Beats": beats
            }
            
            # Ensure levels directory exists
            levels_dir = os.path.join(os.getcwd(), "levels")
            os.makedirs(levels_dir, exist_ok=True)
            
            self.generated_level_path = os.path.join(levels_dir, f"{level_name}.json")
            with open(self.generated_level_path, 'w', encoding='utf-8') as f:
                json.dump(level_data, f, indent=4)
                
            self.lbl_status.setText(f"Success! Generated {len(beats)} beats (BPM: {bpm:.1f}).")
            self.btn_test.setEnabled(True)
            
        except Exception as e:
            self.lbl_status.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to generate level:\n{str(e)}")

    def test_level(self):
        if self.generated_level_path and os.path.exists(self.generated_level_path):
            # Run the main game with the new level
            game_script = os.path.join(os.getcwd(), "main.py")
            if os.path.exists(game_script):
                # Use current python executable to avoid environment issues
                subprocess.Popen([sys.executable, game_script, self.generated_level_path])
            else:
                QMessageBox.warning(self, "Error", "main.py not found in current directory.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LevelGenerator()
    window.show()
    sys.exit(app.exec())
