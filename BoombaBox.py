import sys
import os
import random
import json
from datetime import datetime

try:
    import vlc
except ImportError:
    print("Error: python-vlc not installed. Run: pip install python-vlc")
    sys.exit(1)

try:
    from mutagen import File
    from mutagen.id3 import ID3, APIC
except ImportError:
    print("Error: mutagen not installed. Run: pip install mutagen")
    sys.exit(1)

try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QListWidget, QPushButton, QLabel, QLineEdit,
        QTabWidget, QSplitter, QSlider, QStyle,
        QScrollArea, QGridLayout, QFrame, QFileDialog,
        QMessageBox, QComboBox, QInputDialog, QDialog,
        QListWidgetItem, QMenu, QAction
    )
    from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal
    from PyQt5.QtGui import QPixmap, QImage, QFont, QColor, QCursor
except ImportError:
    print("Error: PyQt5 not installed. Run: pip install PyQt5")
    sys.exit(1)


MUSIC_DIR = "music"
PLAYLISTS_FILE = "playlists.json"
SETTINGS_FILE = "settings.json"


def scan_music_folder(folder):
    """Scan music folder and extract metadata"""
    songs = []
    if not os.path.exists(folder):
        os.makedirs(folder)
        return songs
    
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac")):
                path = os.path.join(root, f)
                try:
                    meta = File(path, easy=True)
                    album_art = None

                    if f.lower().endswith(".mp3"):
                        try:
                            tags = ID3(path)
                            for tag in tags.values():
                                if isinstance(tag, APIC):
                                    album_art = QImage.fromData(tag.data)
                                    break
                        except:
                            pass

                    songs.append({
                        "title": meta.get("title", [os.path.splitext(f)[0]])[0] if meta else os.path.splitext(f)[0],
                        "artist": meta.get("artist", ["Unknown Artist"])[0] if meta else "Unknown Artist",
                        "album": meta.get("album", ["Unknown Album"])[0] if meta else "Unknown Album",
                        "genre": meta.get("genre", ["Unknown Genre"])[0] if meta else "Unknown Genre",
                        "file": path,
                        "art": album_art,
                        "duration": 0,
                        "plays": 0
                    })
                except Exception as e:
                    print(f"Error reading {path}: {e}")
    return songs


class ClickableSlider(QSlider):
    """Custom slider that allows clicking to seek"""
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                event.x(), self.width()
            )
            self.setValue(val)
            self.sliderReleased.emit()
        super().mousePressEvent(event)


class MusicPlayer(QWidget):
    TILE_WIDTH = 180
    TILE_HEIGHT = 260

    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎵 Boomba FM - Music Player")
        self.setGeometry(100, 100, 1200, 750)

        self.vlc_instance = vlc.Instance()
        self.player = self.vlc_instance.media_player_new()

        self.songs = scan_music_folder(MUSIC_DIR)
        self.filtered_songs = self.songs.copy()
        self.current_index = -1
        self.is_shuffle = False
        self.repeat_mode = 0  # 0: no repeat, 1: repeat all, 2: repeat one
        self.shuffle_history = []
        self.play_queue = []
        
        self.playlists = self.load_playlists()
        self.current_playlist = None
        self.settings = self.load_settings()
        self.favorites = self.settings.get("favorites", [])
        self.recent_plays = self.settings.get("recent_plays", [])

        self.init_ui()
        self.apply_theme()

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_progress)
        
        # Auto-save timer
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(30000)  # Save every 30 seconds
        self.save_timer.timeout.connect(self.save_settings)
        self.save_timer.start()
        
        self.player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self.on_song_end)

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # === TOP BAR ===
        top_bar = QHBoxLayout()
        title_label = QLabel("🎵 Boomba FM")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #1db954;")
        top_bar.addWidget(title_label)
        top_bar.addStretch()
        
        self.folder_button = QPushButton("📁 Change Folder")
        self.folder_button.clicked.connect(self.change_music_folder)
        top_bar.addWidget(self.folder_button)
        
        self.refresh_button = QPushButton("🔄 Refresh")
        self.refresh_button.clicked.connect(self.refresh_library)
        top_bar.addWidget(self.refresh_button)
        
        main_layout.addLayout(top_bar)

        # === TABS ===
        self.tabs = QTabWidget()

        # --- LIBRARY TAB ---
        self.library_tab = QWidget()
        lib_layout = QVBoxLayout()

        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 Search by artist, album, genre, title...")
        self.search_bar.textChanged.connect(self.apply_filter)
        search_layout.addWidget(self.search_bar)
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Sort: Default", "Sort: Title", "Sort: Artist", "Sort: Album", "Sort: Most Played"])
        self.sort_combo.currentIndexChanged.connect(self.apply_sort)
        search_layout.addWidget(self.sort_combo)
        
        clear_btn = QPushButton("✖ Clear")
        clear_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(clear_btn)
        
        lib_layout.addLayout(search_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(20)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_widget.setLayout(self.grid_layout)
        self.scroll_area.setWidget(self.grid_widget)
        lib_layout.addWidget(self.scroll_area)

        self.library_tab.setLayout(lib_layout)
        self.tabs.addTab(self.library_tab, "🎵 Library")

        # --- BROWSE TAB ---
        self.browse_tab = QWidget()
        browse_layout = QVBoxLayout()
        
        browse_label = QLabel("Browse by Category")
        browse_label.setFont(QFont("Arial", 12, QFont.Bold))
        browse_layout.addWidget(browse_label)
        
        browse_splitter = QSplitter()
        
        # Artists
        artist_widget = QWidget()
        artist_layout = QVBoxLayout()
        artist_header = QLabel("👤 Artists")
        artist_header.setFont(QFont("Arial", 10, QFont.Bold))
        artist_layout.addWidget(artist_header)
        self.artist_list = QListWidget()
        self.artist_list.itemClicked.connect(lambda: self.filter_by("artist"))
        artist_layout.addWidget(self.artist_list)
        artist_widget.setLayout(artist_layout)
        
        # Albums
        album_widget = QWidget()
        album_layout = QVBoxLayout()
        album_header = QLabel("💿 Albums")
        album_header.setFont(QFont("Arial", 10, QFont.Bold))
        album_layout.addWidget(album_header)
        self.album_list = QListWidget()
        self.album_list.itemClicked.connect(lambda: self.filter_by("album"))
        album_layout.addWidget(self.album_list)
        album_widget.setLayout(album_layout)
        
        # Genres
        genre_widget = QWidget()
        genre_layout = QVBoxLayout()
        genre_header = QLabel("🎸 Genres")
        genre_header.setFont(QFont("Arial", 10, QFont.Bold))
        genre_layout.addWidget(genre_header)
        self.genre_list = QListWidget()
        self.genre_list.itemClicked.connect(lambda: self.filter_by("genre"))
        genre_layout.addWidget(self.genre_list)
        genre_widget.setLayout(genre_layout)

        browse_splitter.addWidget(artist_widget)
        browse_splitter.addWidget(album_widget)
        browse_splitter.addWidget(genre_widget)
        browse_layout.addWidget(browse_splitter)

        self.populate_browse_lists()
        self.browse_tab.setLayout(browse_layout)
        self.tabs.addTab(self.browse_tab, "📂 Browse")

        # --- PLAYLISTS TAB ---
        self.playlists_tab = QWidget()
        playlists_layout = QHBoxLayout()
        
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("📋 Your Playlists"))
        self.playlist_list = QListWidget()
        self.playlist_list.itemClicked.connect(self.load_playlist)
        left_panel.addWidget(self.playlist_list)
        
        playlist_buttons = QHBoxLayout()
        self.new_playlist_btn = QPushButton("➕ New")
        self.new_playlist_btn.clicked.connect(self.create_playlist)
        self.delete_playlist_btn = QPushButton("🗑️ Delete")
        self.delete_playlist_btn.clicked.connect(self.delete_playlist)
        self.rename_playlist_btn = QPushButton("✏️ Rename")
        self.rename_playlist_btn.clicked.connect(self.rename_playlist)
        playlist_buttons.addWidget(self.new_playlist_btn)
        playlist_buttons.addWidget(self.rename_playlist_btn)
        playlist_buttons.addWidget(self.delete_playlist_btn)
        left_panel.addLayout(playlist_buttons)
        
        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("🎵 Playlist Songs"))
        self.playlist_songs_list = QListWidget()
        self.playlist_songs_list.itemDoubleClicked.connect(self.play_from_playlist)
        self.playlist_songs_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_songs_list.customContextMenuRequested.connect(self.show_playlist_context_menu)
        right_panel.addWidget(self.playlist_songs_list)
        
        playlist_song_buttons = QHBoxLayout()
        self.add_to_playlist_btn = QPushButton("➕ Add Songs")
        self.add_to_playlist_btn.clicked.connect(self.add_song_to_playlist)
        self.remove_from_playlist_btn = QPushButton("➖ Remove")
        self.remove_from_playlist_btn.clicked.connect(self.remove_from_playlist)
        self.play_playlist_btn = QPushButton("▶ Play All")
        self.play_playlist_btn.clicked.connect(self.play_entire_playlist)
        playlist_song_buttons.addWidget(self.add_to_playlist_btn)
        playlist_song_buttons.addWidget(self.remove_from_playlist_btn)
        playlist_song_buttons.addWidget(self.play_playlist_btn)
        right_panel.addLayout(playlist_song_buttons)
        
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        
        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        playlists_layout.addWidget(splitter)
        
        self.playlists_tab.setLayout(playlists_layout)
        self.tabs.addTab(self.playlists_tab, "📋 Playlists")
        self.populate_playlist_list()

        # --- FAVORITES TAB ---
        self.favorites_tab = QWidget()
        fav_layout = QVBoxLayout()
        fav_layout.addWidget(QLabel("❤️ Your Favorite Songs"))
        self.favorites_list = QListWidget()
        self.favorites_list.itemDoubleClicked.connect(self.play_from_favorites)
        self.favorites_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.favorites_list.customContextMenuRequested.connect(self.show_favorites_context_menu)
        fav_layout.addWidget(self.favorites_list)
        
        fav_buttons = QHBoxLayout()
        self.remove_fav_btn = QPushButton("➖ Remove from Favorites")
        self.remove_fav_btn.clicked.connect(self.remove_from_favorites)
        self.clear_fav_btn = QPushButton("🗑️ Clear All")
        self.clear_fav_btn.clicked.connect(self.clear_favorites)
        fav_buttons.addWidget(self.remove_fav_btn)
        fav_buttons.addWidget(self.clear_fav_btn)
        fav_layout.addLayout(fav_buttons)
        
        self.favorites_tab.setLayout(fav_layout)
        self.tabs.addTab(self.favorites_tab, "❤️ Favorites")
        self.populate_favorites_list()

        # --- QUEUE TAB ---
        self.queue_tab = QWidget()
        queue_layout = QVBoxLayout()
        queue_layout.addWidget(QLabel("📜 Play Queue"))
        self.queue_list = QListWidget()
        self.queue_list.itemDoubleClicked.connect(self.play_from_queue)
        queue_layout.addWidget(self.queue_list)
        
        queue_buttons = QHBoxLayout()
        self.clear_queue_btn = QPushButton("🗑️ Clear Queue")
        self.clear_queue_btn.clicked.connect(self.clear_queue)
        self.shuffle_queue_btn = QPushButton("🔀 Shuffle Queue")
        self.shuffle_queue_btn.clicked.connect(self.shuffle_queue)
        queue_buttons.addWidget(self.clear_queue_btn)
        queue_buttons.addWidget(self.shuffle_queue_btn)
        queue_layout.addLayout(queue_buttons)
        
        self.queue_tab.setLayout(queue_layout)
        self.tabs.addTab(self.queue_tab, "📜 Queue")

        main_layout.addWidget(self.tabs)

        # === NOW PLAYING INFO ===
        now_playing_frame = QFrame()
        now_playing_frame.setFrameShape(QFrame.StyledPanel)
        now_playing_layout = QHBoxLayout()
        
        self.album_art_label = QLabel()
        self.album_art_label.setFixedSize(70, 70)
        self.album_art_label.setScaledContents(True)
        default_pixmap = QPixmap(70, 70)
        default_pixmap.fill(QColor("#3d3d3d"))
        self.album_art_label.setPixmap(default_pixmap)
        now_playing_layout.addWidget(self.album_art_label)
        
        now_playing_text = QVBoxLayout()
        self.now_playing = QLabel("No song playing")
        self.now_playing.setFont(QFont("Arial", 11, QFont.Bold))
        now_playing_text.addWidget(self.now_playing)
        
        self.now_playing_artist = QLabel("")
        self.now_playing_artist.setStyleSheet("color: #b3b3b3;")
        now_playing_text.addWidget(self.now_playing_artist)
        now_playing_layout.addLayout(now_playing_text)
        now_playing_layout.addStretch()
        
        self.favorite_btn = QPushButton("❤")
        self.favorite_btn.setFixedSize(40, 40)
        self.favorite_btn.clicked.connect(self.toggle_favorite)
        self.favorite_btn.setToolTip("Add to favorites")
        now_playing_layout.addWidget(self.favorite_btn)
        
        self.add_queue_btn = QPushButton("➕")
        self.add_queue_btn.setFixedSize(40, 40)
        self.add_queue_btn.clicked.connect(self.add_current_to_queue)
        self.add_queue_btn.setToolTip("Add to queue")
        now_playing_layout.addWidget(self.add_queue_btn)
        
        now_playing_frame.setLayout(now_playing_layout)
        main_layout.addWidget(now_playing_frame)

        # === PROGRESS BAR ===
        progress_layout = QHBoxLayout()
        self.time_label_start = QLabel("00:00")
        self.time_label_start.setMinimumWidth(45)
        progress_layout.addWidget(self.time_label_start)
        
        self.progress = ClickableSlider(Qt.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.sliderReleased.connect(self.seek_song)
        progress_layout.addWidget(self.progress)
        
        self.time_label_end = QLabel("00:00")
        self.time_label_end.setMinimumWidth(45)
        progress_layout.addWidget(self.time_label_end)
        
        main_layout.addLayout(progress_layout)

        # === CONTROLS ===
        controls = QHBoxLayout()
        
        self.shuffle_button = QPushButton("🔀")
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.clicked.connect(self.toggle_shuffle)
        self.shuffle_button.setToolTip("Shuffle")
        self.shuffle_button.setFixedSize(45, 45)
        controls.addWidget(self.shuffle_button)

        self.prev_button = QPushButton("⏮")
        self.prev_button.clicked.connect(self.prev_song)
        self.prev_button.setFixedSize(45, 45)
        controls.addWidget(self.prev_button)

        self.play_button = QPushButton("▶")
        self.play_button.clicked.connect(self.toggle_play_pause)
        self.play_button.setFixedSize(60, 60)
        play_font = QFont()
        play_font.setPointSize(16)
        self.play_button.setFont(play_font)
        controls.addWidget(self.play_button)

        self.next_button = QPushButton("⏭")
        self.next_button.clicked.connect(self.next_song)
        self.next_button.setFixedSize(45, 45)
        controls.addWidget(self.next_button)

        self.repeat_button = QPushButton("🔁")
        self.repeat_button.clicked.connect(self.cycle_repeat)
        self.repeat_button.setToolTip("Repeat")
        self.repeat_button.setFixedSize(45, 45)
        controls.addWidget(self.repeat_button)
        
        controls.addStretch()
        
        # Volume control
        volume_layout = QHBoxLayout()
        self.volume_icon = QLabel("🔊")
        volume_layout.addWidget(self.volume_icon)
        self.volume_slider = ClickableSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setMaximumWidth(120)
        self.volume_slider.valueChanged.connect(self.change_volume)
        volume_layout.addWidget(self.volume_slider)
        self.volume_label = QLabel("70%")
        self.volume_label.setMinimumWidth(40)
        volume_layout.addWidget(self.volume_label)
        controls.addLayout(volume_layout)

        main_layout.addLayout(controls)

        # === STATS ===
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel(f"📊 Total: {len(self.songs)} songs")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        
        self.queue_status = QLabel(f"📜 Queue: 0 songs")
        stats_layout.addWidget(self.queue_status)
        
        main_layout.addLayout(stats_layout)

        self.setLayout(main_layout)
        self.populate_song_grid()
        self.change_volume()
        self.update_stats()

    def apply_theme(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QWidget {
                background-color: #121212;
                color: #ffffff;
            }
            QPushButton {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 8px;
                padding: 8px;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                border: 1px solid #1db954;
            }
            QPushButton:pressed {
                background-color: #1db954;
            }
            QPushButton:checked {
                background-color: #1db954;
                border: 2px solid #1ed760;
            }
            QLineEdit {
                background-color: #2d2d2d;
                border: 2px solid #3d3d3d;
                border-radius: 8px;
                padding: 10px;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 2px solid #1db954;
            }
            QListWidget {
                background-color: #181818;
                border: 1px solid #3d3d3d;
                border-radius: 8px;
                color: #ffffff;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #1db954;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #2d2d2d;
            }
            QTabWidget::pane {
                border: 1px solid #3d3d3d;
                border-radius: 8px;
                background-color: #181818;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #b3b3b3;
                padding: 10px 20px;
                margin: 2px;
                border-radius: 6px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #1db954;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #3d3d3d;
            }
            QSlider::groove:horizontal {
                border: 1px solid #3d3d3d;
                height: 6px;
                background: #2d2d2d;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1db954;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #1ed760;
            }
            QComboBox {
                background-color: #2d2d2d;
                border: 2px solid #3d3d3d;
                border-radius: 8px;
                padding: 8px;
                color: #ffffff;
            }
            QComboBox:hover {
                border: 2px solid #1db954;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d;
                selection-background-color: #1db954;
            }
            QFrame {
                background-color: #181818;
                border-radius: 10px;
                padding: 5px;
            }
            QScrollArea {
                border: none;
            }
            QLabel {
                color: #ffffff;
            }
        """)

    def populate_song_grid(self):
        """Populate the grid with song tiles"""
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        if not self.filtered_songs:
            no_songs = QLabel("No songs found. Add music to your library!")
            no_songs.setAlignment(Qt.AlignCenter)
            no_songs.setStyleSheet("color: #b3b3b3; font-size: 14px;")
            self.grid_layout.addWidget(no_songs, 0, 0)
            return

        columns = max(1, (self.scroll_area.width() - 60) // (self.TILE_WIDTH + 20))
        row = 0
        col = 0

        for idx, song in enumerate(self.filtered_songs):
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFixedSize(self.TILE_WIDTH, self.TILE_HEIGHT)
            frame.setCursor(Qt.PointingHandCursor)
            frame.setStyleSheet("""
                QFrame {
                    background-color: #1a1a1a;
                    border-radius: 10px;
                    padding: 8px;
                }
                QFrame:hover {
                    background-color: #2d2d2d;
                }
            """)
            
            v_layout = QVBoxLayout()
            v_layout.setContentsMargins(8, 8, 8, 8)
            v_layout.setSpacing(5)

            # Album art
            if song["art"]:
                pixmap = QPixmap.fromImage(song["art"])
            else:
                pixmap = QPixmap(self.TILE_WIDTH - 16, 150)
                pixmap.fill(QColor("#3d3d3d"))
            
            label_art = QLabel()
            label_art.setPixmap(pixmap.scaled(self.TILE_WIDTH - 16, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            label_art.setAlignment(Qt.AlignCenter)
            label_art.setStyleSheet("border-radius: 8px;")
            v_layout.addWidget(label_art)

            # Title
            title_text = song["title"][:35] + "..." if len(song["title"]) > 35 else song["title"]
            label_title = QLabel(title_text)
            label_title.setAlignment(Qt.AlignCenter)
            label_title.setWordWrap(True)
            label_title.setFont(QFont("Arial", 9, QFont.Bold))
            label_title.setStyleSheet("color: #ffffff;")
            v_layout.addWidget(label_title)

            # Artist
            artist_text = song["artist"][:30] + "..." if len(song["artist"]) > 30 else song["artist"]
            label_artist = QLabel(artist_text)
            label_artist.setAlignment(Qt.AlignCenter)
            label_artist.setStyleSheet("color: #b3b3b3; font-size: 8pt;")
            v_layout.addWidget(label_artist)

            # Play count
            if song.get("plays", 0) > 0:
                plays_label = QLabel(f"▶ {song['plays']} plays")
                plays_label.setAlignment(Qt.AlignCenter)
                plays_label.setStyleSheet("color: #1db954; font-size: 7pt;")
                v_layout.addWidget(plays_label)

            v_layout.addStretch()
            frame.setLayout(v_layout)
            frame.mouseDoubleClickEvent = lambda e, index=idx: self.play_song(index)
            frame.setContextMenuPolicy(Qt.CustomContextMenu)
            frame.customContextMenuRequested.connect(lambda pos, index=idx: self.show_song_context_menu(index))

            self.grid_layout.addWidget(frame, row, col)
            col += 1
            if col >= columns:
                col = 0
                row += 1

    def show_song_context_menu(self, index):
        """Show context menu for song tiles"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
            }
            QMenu::item:selected {
                background-color: #1db954;
            }
        """)
        
        play_action = QAction("▶ Play", self)
        play_action.triggered.connect(lambda: self.play_song(index))
        menu.addAction(play_action)
        
        queue_action = QAction("➕ Add to Queue", self)
        queue_action.triggered.connect(lambda: self.add_to_queue(index))
        menu.addAction(queue_action)
        
        menu.addSeparator()
        
        playlist_menu = menu.addMenu("📋 Add to Playlist")
        for playlist_name in self.playlists.keys():
            action = QAction(playlist_name, self)
            action.triggered.connect(lambda checked, pname=playlist_name, idx=index: self.quick_add_to_playlist(pname, idx))
            playlist_menu.addAction(action)
        
        fav_action = QAction("❤ Add to Favorites", self)
        fav_action.triggered.connect(lambda: self.add_to_favorites_by_index(index))
        menu.addAction(fav_action)
        
        menu.exec_(QCursor.pos())

    def populate_browse_lists(self):
        """Populate browse lists with categories"""
        self.artist_list.clear()
        self.album_list.clear()
        self.genre_list.clear()
        
        if not self.songs:
            return
            
        artists = sorted(set(s["artist"] for s in self.songs))
        albums = sorted(set(s["album"] for s in self.songs))
        genres = sorted(set(s["genre"] for s in self.songs))
        
        for artist in artists:
            count = len([s for s in self.songs if s["artist"] == artist])
            self.artist_list.addItem(f"{artist} ({count})")
        
        for album in albums:
            count = len([s for s in self.songs if s["album"] == album])
            self.album_list.addItem(f"{album} ({count})")
        
        for genre in genres:
            count = len([s for s in self.songs if s["genre"] == genre])
            self.genre_list.addItem(f"{genre} ({count})")

    def apply_filter(self, text):
        """Filter songs based on search text"""
        text = text.lower()
        self.filtered_songs = [
            s for s in self.songs
            if text in s["artist"].lower()
            or text in s["album"].lower()
            or text in s["genre"].lower()
            or text in s["title"].lower()
        ]
        self.apply_sort(self.sort_combo.currentIndex())

    def apply_sort(self, index):
        """Sort filtered songs"""
        if index == 1:  # Title
            self.filtered_songs.sort(key=lambda x: x["title"].lower())
        elif index == 2:  # Artist
            self.filtered_songs.sort(key=lambda x: x["artist"].lower())
        elif index == 3:  # Album
            self.filtered_songs.sort(key=lambda x: x["album"].lower())
        elif index == 4:  # Most Played
            self.filtered_songs.sort(key=lambda x: x.get("plays", 0), reverse=True)
        self.populate_song_grid()
        self.update_stats()

    def clear_search(self):
        """Clear search and filters"""
        self.search_bar.clear()
        self.filtered_songs = self.songs.copy()
        self.sort_combo.setCurrentIndex(0)
        self.populate_song_grid()
        self.update_stats()

    def filter_by(self, field):
        """Filter by specific field from browse tab"""
        item = self.sender().currentItem()
        if not item:
            return
        value = item.text().rsplit(" (", 1)[0]  # Remove count
        self.filtered_songs = [s for s in self.songs if s[field] == value]
        self.populate_song_grid()
        self.tabs.setCurrentWidget(self.library_tab)
        self.update_stats()

    def play_song(self, row=None):
        """Play a song at the given index"""
        if row is None:
            return
        if row < 0 or row >= len(self.filtered_songs):
            return

        self.current_index = row
        song = self.filtered_songs[row]

        media = self.vlc_instance.media_new(song["file"])
        self.player.set_media(media)
        self.player.play()
        self.player.audio_set_volume(self.volume_slider.value())

        self.play_button.setText("⏸")
        self.now_playing.setText(song['title'])
        self.now_playing_artist.setText(f"{song['artist']} • {song['album']}")
        
        # Update album art
        if song["art"]:
            pixmap = QPixmap.fromImage(song["art"])
            self.album_art_label.setPixmap(pixmap.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            pixmap = QPixmap(70, 70)
            pixmap.fill(QColor("#3d3d3d"))
            self.album_art_label.setPixmap(pixmap)
        
        # Update favorite button
        if song["file"] in self.favorites:
            self.favorite_btn.setText("💚")
            self.favorite_btn.setStyleSheet("background-color: #1db954;")
        else:
            self.favorite_btn.setText("❤")
            self.favorite_btn.setStyleSheet("")
        
        self.timer.start()
        
        # Track play count
        song["plays"] = song.get("plays", 0) + 1
        self.add_to_recent_plays(song["file"])
        
        if self.is_shuffle and row not in self.shuffle_history:
            self.shuffle_history.append(row)

    def toggle_play_pause(self):
        """Toggle between play and pause"""
        if self.player.is_playing():
            self.player.pause()
            self.play_button.setText("▶")
        else:
            if self.current_index == -1 and self.filtered_songs:
                self.play_song(0)
            else:
                self.player.play()
                self.play_button.setText("⏸")

    def next_song(self):
        """Play next song"""
        # Check queue first
        if self.play_queue:
            song_file = self.play_queue.pop(0)
            self.update_queue_display()
            song = next((s for s in self.songs if s["file"] == song_file), None)
            if song and song in self.filtered_songs:
                self.current_index = self.filtered_songs.index(song)
                self.play_song(self.current_index)
                return
        
        if not self.filtered_songs:
            return
        
        if self.is_shuffle:
            unplayed = [i for i in range(len(self.filtered_songs)) if i not in self.shuffle_history]
            if unplayed:
                self.current_index = random.choice(unplayed)
            else:
                self.shuffle_history.clear()
                self.current_index = random.randint(0, len(self.filtered_songs) - 1)
        else:
            if self.current_index < len(self.filtered_songs) - 1:
                self.current_index += 1
            elif self.repeat_mode == 1:
                self.current_index = 0
            else:
                return
        
        self.play_song(self.current_index)

    def prev_song(self):
        """Play previous song"""
        if not self.filtered_songs:
            return
        
        # If more than 3 seconds played, restart current song
        if self.player.get_time() > 3000:
            self.player.set_time(0)
            return
        
        if self.current_index > 0:
            self.current_index -= 1
            self.play_song(self.current_index)
        elif self.repeat_mode == 1:
            self.current_index = len(self.filtered_songs) - 1
            self.play_song(self.current_index)

    def on_song_end(self, event):
        """Handle song end event"""
        if self.repeat_mode == 2:  # Repeat one
            self.play_song(self.current_index)
        else:
            self.next_song()

    def toggle_shuffle(self):
        """Toggle shuffle mode"""
        self.is_shuffle = self.shuffle_button.isChecked()
        if self.is_shuffle:
            self.shuffle_history.clear()
            self.shuffle_button.setStyleSheet("background-color: #1db954;")
        else:
            self.shuffle_button.setStyleSheet("")

    def cycle_repeat(self):
        """Cycle through repeat modes"""
        self.repeat_mode = (self.repeat_mode + 1) % 3
        if self.repeat_mode == 0:
            self.repeat_button.setToolTip("Repeat: Off")
            self.repeat_button.setStyleSheet("")
            self.repeat_button.setText("🔁")
        elif self.repeat_mode == 1:
            self.repeat_button.setToolTip("Repeat: All")
            self.repeat_button.setStyleSheet("background-color: #1db954;")
            self.repeat_button.setText("🔁")
        else:
            self.repeat_button.setToolTip("Repeat: One")
            self.repeat_button.setStyleSheet("background-color: #1db954;")
            self.repeat_button.setText("🔂")

    def change_volume(self):
        """Change volume"""
        volume = self.volume_slider.value()
        self.player.audio_set_volume(volume)
        self.volume_label.setText(f"{volume}%")
        
        if volume == 0:
            self.volume_icon.setText("🔇")
        elif volume < 50:
            self.volume_icon.setText("🔉")
        else:
            self.volume_icon.setText("🔊")

    def update_progress(self):
        """Update progress bar and time labels"""
        if not self.player:
            return
        length = self.player.get_length()
        pos = self.player.get_time()

        if length > 0:
            self.progress.blockSignals(True)
            self.progress.setValue(int(pos / length * 1000))
            self.progress.blockSignals(False)

            elapsed = self.format_time(pos // 1000)
            total = self.format_time(length // 1000)
            self.time_label_start.setText(elapsed)
            self.time_label_end.setText(total)

    def seek_song(self):
        """Seek to position in song"""
        if not self.player:
            return
        length = self.player.get_length()
        if length > 0:
            val = self.progress.value() / 1000
            self.player.set_time(int(val * length))

    def change_music_folder(self):
        """Change music folder and rescan"""
        folder = QFileDialog.getExistingDirectory(self, "Select Music Folder")
        if folder:
            global MUSIC_DIR
            MUSIC_DIR = folder
            self.refresh_library()
            QMessageBox.information(self, "Success", f"Loaded {len(self.songs)} songs from {folder}")

    def refresh_library(self):
        """Refresh music library"""
        self.songs = scan_music_folder(MUSIC_DIR)
        self.filtered_songs = self.songs.copy()
        self.populate_song_grid()
        self.populate_browse_lists()
        self.update_stats()
        QMessageBox.information(self, "Refreshed", f"Library updated with {len(self.songs)} songs")

    def update_stats(self):
        """Update statistics display"""
        self.stats_label.setText(f"📊 Showing {len(self.filtered_songs)} of {len(self.songs)} songs")
        self.queue_status.setText(f"📜 Queue: {len(self.play_queue)} songs")

    # === PLAYLIST FUNCTIONS ===
    
    def load_playlists(self):
        """Load playlists from file"""
        if os.path.exists(PLAYLISTS_FILE):
            try:
                with open(PLAYLISTS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_playlists(self):
        """Save playlists to file"""
        with open(PLAYLISTS_FILE, 'w') as f:
            json.dump(self.playlists, f, indent=2)

    def populate_playlist_list(self):
        """Populate playlist list"""
        self.playlist_list.clear()
        for name in sorted(self.playlists.keys()):
            count = len(self.playlists[name])
            self.playlist_list.addItem(f"{name} ({count} songs)")

    def create_playlist(self):
        """Create new playlist"""
        name, ok = QInputDialog.getText(self, "New Playlist", "Enter playlist name:")
        if ok and name:
            if name not in self.playlists:
                self.playlists[name] = []
                self.save_playlists()
                self.populate_playlist_list()
                QMessageBox.information(self, "Success", f"Playlist '{name}' created!")
            else:
                QMessageBox.warning(self, "Error", "Playlist already exists!")

    def rename_playlist(self):
        """Rename selected playlist"""
        item = self.playlist_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Error", "Please select a playlist first!")
            return
        
        old_name = item.text().rsplit(" (", 1)[0]
        new_name, ok = QInputDialog.getText(self, "Rename Playlist", "Enter new name:", text=old_name)
        
        if ok and new_name and new_name != old_name:
            if new_name not in self.playlists:
                self.playlists[new_name] = self.playlists.pop(old_name)
                self.save_playlists()
                self.populate_playlist_list()
                if self.current_playlist == old_name:
                    self.current_playlist = new_name
                QMessageBox.information(self, "Success", f"Playlist renamed to '{new_name}'")
            else:
                QMessageBox.warning(self, "Error", "A playlist with that name already exists!")

    def delete_playlist(self):
        """Delete selected playlist"""
        item = self.playlist_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Error", "Please select a playlist first!")
            return
        
        name = item.text().rsplit(" (", 1)[0]
        reply = QMessageBox.question(self, "Delete Playlist", 
                                     f"Delete playlist '{name}'?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            del self.playlists[name]
            self.save_playlists()
            self.populate_playlist_list()
            self.playlist_songs_list.clear()
            if self.current_playlist == name:
                self.current_playlist = None

    def load_playlist(self, item):
        """Load playlist songs"""
        self.current_playlist = item.text().rsplit(" (", 1)[0]
        self.playlist_songs_list.clear()
        for song_path in self.playlists[self.current_playlist]:
            song = next((s for s in self.songs if s["file"] == song_path), None)
            if song:
                self.playlist_songs_list.addItem(f"{song['title']} - {song['artist']}")

    def add_song_to_playlist(self):
        """Add songs to current playlist"""
        if not self.current_playlist:
            QMessageBox.warning(self, "Error", "Please select a playlist first!")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Songs to Playlist")
        dialog.setGeometry(300, 300, 500, 600)
        layout = QVBoxLayout()
        
        search = QLineEdit()
        search.setPlaceholderText("🔍 Search songs...")
        layout.addWidget(search)
        
        song_list = QListWidget()
        song_list.setSelectionMode(QListWidget.MultiSelection)
        
        def populate_dialog():
            song_list.clear()
            search_text = search.text().lower()
            for song in self.songs:
                if (not search_text or 
                    search_text in song['title'].lower() or 
                    search_text in song['artist'].lower()):
                    item = QListWidgetItem(f"{song['title']} - {song['artist']}")
                    item.setData(Qt.UserRole, song['file'])
                    song_list.addItem(item)
        
        search.textChanged.connect(populate_dialog)
        populate_dialog()
        layout.addWidget(song_list)
        
        button_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Selected")
        cancel_btn = QPushButton("Cancel")
        
        def add_selected():
            added = 0
            for item in song_list.selectedItems():
                song_path = item.data(Qt.UserRole)
                if song_path not in self.playlists[self.current_playlist]:
                    self.playlists[self.current_playlist].append(song_path)
                    added += 1
            self.save_playlists()
            self.load_playlist(self.playlist_list.currentItem())
            self.populate_playlist_list()
            QMessageBox.information(dialog, "Success", f"Added {added} song(s) to playlist!")
            dialog.close()
        
        add_btn.clicked.connect(add_selected)
        cancel_btn.clicked.connect(dialog.close)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        dialog.exec_()

    def quick_add_to_playlist(self, playlist_name, song_index):
        """Quickly add song to playlist from context menu"""
        song = self.filtered_songs[song_index]
        if song["file"] not in self.playlists[playlist_name]:
            self.playlists[playlist_name].append(song["file"])
            self.save_playlists()
            QMessageBox.information(self, "Success", f"Added to '{playlist_name}'!")

    def remove_from_playlist(self):
        """Remove song from current playlist"""
        if not self.current_playlist:
            return
        idx = self.playlist_songs_list.currentRow()
        if idx >= 0:
            del self.playlists[self.current_playlist][idx]
            self.save_playlists()
            self.load_playlist(self.playlist_list.currentItem())
            self.populate_playlist_list()

    def play_from_playlist(self, item):
        """Play song from playlist"""
        if not self.current_playlist:
            return
        idx = self.playlist_songs_list.row(item)
        song_path = self.playlists[self.current_playlist][idx]
        song = next((s for s in self.songs if s["file"] == song_path), None)
        if song:
            self.filtered_songs = [s for s_path in self.playlists[self.current_playlist] 
                                  for s in self.songs if s["file"] == s_path]
            self.current_index = idx
            self.play_song(idx)

    def play_entire_playlist(self):
        """Play all songs in current playlist"""
        if not self.current_playlist or not self.playlists[self.current_playlist]:
            QMessageBox.warning(self, "Error", "Playlist is empty!")
            return
        
        self.filtered_songs = [s for s_path in self.playlists[self.current_playlist] 
                              for s in self.songs if s["file"] == s_path]
        self.current_index = 0
        self.play_song(0)
        self.tabs.setCurrentWidget(self.library_tab)

    def show_playlist_context_menu(self, pos):
        """Show context menu for playlist songs"""
        item = self.playlist_songs_list.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        play_action = QAction("▶ Play", self)
        play_action.triggered.connect(lambda: self.play_from_playlist(item))
        menu.addAction(play_action)
        
        remove_action = QAction("➖ Remove", self)
        remove_action.triggered.connect(self.remove_from_playlist)
        menu.addAction(remove_action)
        
        menu.exec_(QCursor.pos())

    # === FAVORITES FUNCTIONS ===
    
    def populate_favorites_list(self):
        """Populate favorites list"""
        self.favorites_list.clear()
        for fav_path in self.favorites:
            song = next((s for s in self.songs if s["file"] == fav_path), None)
            if song:
                self.favorites_list.addItem(f"{song['title']} - {song['artist']}")

    def toggle_favorite(self):
        """Toggle favorite status of current song"""
        if self.current_index < 0 or not self.filtered_songs:
            return
        
        song = self.filtered_songs[self.current_index]
        if song["file"] in self.favorites:
            self.favorites.remove(song["file"])
            self.favorite_btn.setText("❤")
            self.favorite_btn.setStyleSheet("")
        else:
            self.favorites.append(song["file"])
            self.favorite_btn.setText("💚")
            self.favorite_btn.setStyleSheet("background-color: #1db954;")
        
        self.populate_favorites_list()
        self.save_settings()

    def add_to_favorites_by_index(self, index):
        """Add song to favorites by index"""
        song = self.filtered_songs[index]
        if song["file"] not in self.favorites:
            self.favorites.append(song["file"])
            self.populate_favorites_list()
            self.save_settings()
            QMessageBox.information(self, "Success", "Added to favorites!")

    def remove_from_favorites(self):
        """Remove selected song from favorites"""
        idx = self.favorites_list.currentRow()
        if idx >= 0 and idx < len(self.favorites):
            del self.favorites[idx]
            self.populate_favorites_list()
            self.save_settings()

    def clear_favorites(self):
        """Clear all favorites"""
        reply = QMessageBox.question(self, "Clear Favorites",
                                     "Remove all songs from favorites?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.favorites.clear()
            self.populate_favorites_list()
            self.save_settings()

    def play_from_favorites(self, item):
        """Play song from favorites"""
        idx = self.favorites_list.row(item)
        if idx >= 0 and idx < len(self.favorites):
            song_path = self.favorites[idx]
            song = next((s for s in self.songs if s["file"] == song_path), None)
            if song and song in self.songs:
                self.filtered_songs = [s for s in self.songs if s["file"] in self.favorites]
                self.current_index = self.filtered_songs.index(song)
                self.play_song(self.current_index)

    def show_favorites_context_menu(self, pos):
        """Show context menu for favorites"""
        item = self.favorites_list.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        play_action = QAction("▶ Play", self)
        play_action.triggered.connect(lambda: self.play_from_favorites(item))
        menu.addAction(play_action)
        
        remove_action = QAction("➖ Remove from Favorites", self)
        remove_action.triggered.connect(self.remove_from_favorites)
        menu.addAction(remove_action)
        
        menu.exec_(QCursor.pos())

    # === QUEUE FUNCTIONS ===
    
    def add_to_queue(self, index):
        """Add song to play queue"""
        song = self.filtered_songs[index]
        if song["file"] not in self.play_queue:
            self.play_queue.append(song["file"])
            self.update_queue_display()
            QMessageBox.information(self, "Queue", f"Added '{song['title']}' to queue!")

    def add_current_to_queue(self):
        """Add current song to queue"""
        if self.current_index >= 0 and self.filtered_songs:
            self.add_to_queue(self.current_index)

    def update_queue_display(self):
        """Update queue list display"""
        self.queue_list.clear()
        for song_path in self.play_queue:
            song = next((s for s in self.songs if s["file"] == song_path), None)
            if song:
                self.queue_list.addItem(f"{song['title']} - {song['artist']}")
        self.update_stats()

    def clear_queue(self):
        """Clear play queue"""
        self.play_queue.clear()
        self.update_queue_display()

    def shuffle_queue(self):
        """Shuffle play queue"""
        random.shuffle(self.play_queue)
        self.update_queue_display()

    def play_from_queue(self, item):
        """Play specific song from queue"""
        idx = self.queue_list.row(item)
        if idx >= 0 and idx < len(self.play_queue):
            song_path = self.play_queue.pop(idx)
            self.update_queue_display()
            song = next((s for s in self.songs if s["file"] == song_path), None)
            if song and song in self.filtered_songs:
                self.current_index = self.filtered_songs.index(song)
                self.play_song(self.current_index)

    # === SETTINGS FUNCTIONS ===
    
    def load_settings(self):
        """Load user settings"""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_settings(self):
        """Save user settings"""
        self.settings["favorites"] = self.favorites
        self.settings["recent_plays"] = self.recent_plays
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=2)

    def add_to_recent_plays(self, song_path):
        """Add song to recent plays"""
        if song_path in self.recent_plays:
            self.recent_plays.remove(song_path)
        self.recent_plays.insert(0, song_path)
        self.recent_plays = self.recent_plays[:50]  # Keep last 50

    @staticmethod
    def format_time(seconds):
        """Format seconds to MM:SS or HH:MM:SS"""
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02}:{m:02}:{s:02}"
        return f"{m:02}:{s:02}"

    def closeEvent(self, event):
        """Handle window close event"""
        self.save_settings()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = MusicPlayer()
    player.show()
    sys.exit(app.exec_())