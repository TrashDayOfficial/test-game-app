import pyglet
from pyglet import shapes
from pyglet import gl
import random
import math
import socket
import threading
import json
import struct
import time

# Constants
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60
NETWORK_PORT = 5555

# World settings
WORLD_WIDTH = 4000  # 5x screen width
WORLD_HEIGHT = 3000  # 5x screen height

# Colors (RGB for pyglet shapes)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)  # Bright green for player (very visible on black)
CYAN = (0, 255, 255)  # Bright cyan
BLUE = (100, 150, 255)
YELLOW = (255, 255, 0)
ORANGE = (255, 165, 0)

# Player settings
PLAYER_SIZE = 30
PLAYER_SPEED = 300  # Pixels per second (time-based movement)

# Projectile settings
PROJECTILE_SIZE = 10
PROJECTILE_SPEED = 10

# Enemy settings
ENEMY_SIZE = 25
ENEMY_SPEED = 2
INITIAL_ENEMY_SPAWN_RATE = 60  # Initial spawn rate (spawns every N frames)
MIN_ENEMY_SPAWN_RATE = 20  # Minimum spawn rate (fastest spawning)
MAX_ENEMIES = 10
ENEMY_SPAWN_ACCELERATION = 0.5  # How fast spawn rate decreases (frames per second)

# Rock settings
ROCK_MIN_SIZE = 40
ROCK_MAX_SIZE = 120
MAX_ROCKS = 50  # Generate this many rocks at game start

# Tree settings
TREE_SIZE = 25  # Smaller than rocks
MAX_TREES = 80  # Generate this many trees at game start
TREE_CHOP_TIME = 2.0  # Time in seconds to chop down a tree

class Camera:
    """Camera that follows the player"""
    def __init__(self):
        self.x = 0
        self.y = 0
        self.target_x = 0
        self.target_y = 0
        self.first_update = True  # Track first update for instant snap
    
    def update(self, target_x, target_y):
        """Update camera to follow target (player)"""
        # Center camera on player
        self.target_x = target_x - SCREEN_WIDTH // 2
        self.target_y = target_y - SCREEN_HEIGHT // 2
        
        # On first update, snap immediately to position
        if self.first_update:
            self.x = self.target_x
            self.y = self.target_y
            self.first_update = False
        else:
            # Smooth camera movement (lerp)
            self.x += (self.target_x - self.x) * 0.1
            self.y += (self.target_y - self.y) * 0.1
        
        # Keep camera within world bounds
        self.x = max(0, min(WORLD_WIDTH - SCREEN_WIDTH, self.x))
        self.y = max(0, min(WORLD_HEIGHT - SCREEN_HEIGHT, self.y))
    
    def world_to_screen(self, world_x, world_y):
        """Convert world coordinates to screen coordinates"""
        return (world_x - self.x, world_y - self.y)
    
    def screen_to_world(self, screen_x, screen_y):
        """Convert screen coordinates to world coordinates"""
        return (screen_x + self.x, screen_y + self.y)

class Player:
    def __init__(self, x, y, batch, color=GREEN, player_id=1):
        self.x = x
        self.y = y
        self.size = PLAYER_SIZE
        self.speed = PLAYER_SPEED
        self.batch = batch
        self.player_id = player_id
        # Track last movement direction for shooting
        self.last_direction_x = 0
        self.last_direction_y = 1  # Default: facing up
        # Track velocity for projectile inheritance
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        # Resources
        self.wood = 0
        # Create a solid color image for the player sprite
        format = 'RGBA'
        pitch = self.size * len(format)
        data = bytes(color + (255,)) * (self.size * self.size)  # RGBA bytes
        self.image = pyglet.image.ImageData(self.size, self.size, format, data, pitch=-pitch)
        # Initial sprite position (will be updated by camera)
        # Position at center of screen initially
        self.sprite = pyglet.sprite.Sprite(self.image, x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2, batch=batch)
        self.sprite.visible = True
        
    def update(self, keys, dt, rocks=None, trees=None):
        # Track movement direction
        move_x = 0
        move_y = 0
        
        # Store old position for collision checking
        old_x = self.x
        old_y = self.y
        new_x = self.x
        new_y = self.y
        
        # Calculate intended movement (WASD only, arrow keys are for shooting)
        # Time-based movement (pixels per second * dt)
        if keys[pyglet.window.key.W]:
            new_y += self.speed * dt
            move_y += 1
        if keys[pyglet.window.key.S]:
            new_y -= self.speed * dt
            move_y -= 1
        if keys[pyglet.window.key.A]:
            new_x -= self.speed * dt
            move_x -= 1
        if keys[pyglet.window.key.D]:
            new_x += self.speed * dt
            move_x += 1
        
        # Check collision with rocks and trees before moving
        player_rect = (new_x, new_y, self.size, self.size)
        can_move_x = True
        can_move_y = True
        
        # Check collision with all obstacles (rocks and trees)
        obstacles_to_check = []
        if rocks:
            obstacles_to_check.extend(rocks)
        if trees:
            # Only check collision with non-chopped trees
            obstacles_to_check.extend([t for t in trees if not t.is_chopped])
        
        for obstacle in obstacles_to_check:
            if check_collision(player_rect, obstacle.get_rect()):
                # Try moving only X or only Y
                test_x = (new_x, old_y, self.size, self.size)
                test_y = (old_x, new_y, self.size, self.size)
                
                if check_collision(test_x, obstacle.get_rect()):
                    can_move_x = False
                if check_collision(test_y, obstacle.get_rect()):
                    can_move_y = False
        
        # Calculate velocity (for projectile inheritance) - in pixels per second
        if dt > 0:
            if can_move_x:
                self.velocity_x = (new_x - old_x) / dt
            else:
                self.velocity_x = 0
            if can_move_y:
                self.velocity_y = (new_y - old_y) / dt
            else:
                self.velocity_y = 0
        else:
            self.velocity_x = 0
            self.velocity_y = 0
        
        # Apply movement based on collision check
        if can_move_x:
            self.x = new_x
        if can_move_y:
            self.y = new_y
        
        # Update last direction if moving
        if move_x != 0 or move_y != 0:
            self.last_direction_x = move_x
            self.last_direction_y = move_y
        
        # Keep player within world bounds
        self.x = max(self.size // 2, min(WORLD_WIDTH - self.size // 2, self.x))
        self.y = max(self.size // 2, min(WORLD_HEIGHT - self.size // 2, self.y))
        
        # Sprite position will be updated by camera in game loop
    
    def update_sprite_position(self, camera):
        """Update sprite position based on camera"""
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        self.sprite.x = screen_x
        self.sprite.y = screen_y
    
    def update_position(self, x, y):
        """Update position from network (for multiplayer)"""
        self.x = x
        self.y = y
        # Sprite position will be updated by camera in game loop
    
    def get_shoot_direction(self):
        """Return the direction the player should shoot (normalized)"""
        return (self.last_direction_x, self.last_direction_y)
    
    def get_center(self):
        return (self.x + self.size / 2, self.y + self.size / 2)
    
    def get_rect(self):
        return (self.x, self.y, self.size, self.size)
    
    def to_dict(self):
        """Serialize player state for networking"""
        return {
            'id': self.player_id,
            'x': self.x,
            'y': self.y
        }

class Projectile:
    def __init__(self, x, y, direction_x, direction_y, batch, owner_id=1, player_velocity_x=0, player_velocity_y=0):
        self.x = x  # World coordinates
        self.y = y
        self.size = PROJECTILE_SIZE
        self.speed = PROJECTILE_SPEED
        self.owner_id = owner_id
        # Normalize direction
        length = math.sqrt(direction_x**2 + direction_y**2)
        if length > 0:
            base_dx = (direction_x / length) * self.speed
            base_dy = (direction_y / length) * self.speed
        else:
            base_dx = 0
            base_dy = self.speed  # Default: shoot up
        
        # Add player velocity to projectile (inherit momentum)
        # player_velocity is in pixels per second, convert to per-frame (divide by FPS)
        # This gives projectiles the player's movement momentum
        velocity_per_frame_x = player_velocity_x / 60.0  # Convert to per-frame
        velocity_per_frame_y = player_velocity_y / 60.0
        self.dx = base_dx + velocity_per_frame_x
        self.dy = base_dy + velocity_per_frame_y
        
        self.batch = batch
        self.shape = shapes.Circle(0, 0, self.size // 2, color=YELLOW, batch=batch)
    
    def update(self):
        self.x += self.dx
        self.y += self.dy
        # Shape position will be updated by camera in game loop
    
    def update_shape_position(self, camera):
        """Update shape position based on camera"""
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        self.shape.x = screen_x + self.size/2
        self.shape.y = screen_y + self.size/2
    
    def is_off_world(self):
        """Check if projectile is outside world bounds"""
        return (self.x < -self.size or self.x > WORLD_WIDTH + self.size or 
                self.y < -self.size or self.y > WORLD_HEIGHT + self.size)
    
    def get_rect(self):
        return (self.x, self.y, self.size, self.size)

class Enemy:
    def __init__(self, x, y, batch, enemy_id=None):
        self.x = x  # World coordinates
        self.y = y
        self.size = ENEMY_SIZE
        self.speed = ENEMY_SPEED
        self.batch = batch
        self.enemy_id = enemy_id or random.randint(1000, 9999)
        # Shapes will be positioned by camera
        self.shape = shapes.Rectangle(0, 0, self.size, self.size, color=RED, batch=batch)
        self.border = shapes.Rectangle(0, 0, self.size, self.size, color=WHITE, batch=batch)
        self.border.opacity = 128  # Make border semi-transparent
    
    def update(self, player_x, player_y, dt, rocks=None):
        # Chase the player (time-based movement for consistent speed)
        dx = player_x - self.x
        dy = player_y - self.y
        distance = math.sqrt(dx**2 + dy**2)
        
        if distance > 0:
            # Calculate intended movement
            speed_per_frame = self.speed * dt * 60  # Convert to frame-based equivalent
            new_x = self.x + (dx / distance) * speed_per_frame
            new_y = self.y + (dy / distance) * speed_per_frame
            
            # Store old position
            old_x = self.x
            old_y = self.y
            
            # Check collision with obstacles (rocks and trees) before moving
            enemy_rect = (new_x, new_y, self.size, self.size)
            can_move_x = True
            can_move_y = True
            
            if rocks:
                for obstacle in rocks:
                    # Handle both Rock and Tree objects
                    if hasattr(obstacle, 'is_chopped') and obstacle.is_chopped:
                        continue  # Skip chopped trees
                    if check_collision(enemy_rect, obstacle.get_rect()):
                        # Try moving only X or only Y
                        test_x = (new_x, old_y, self.size, self.size)
                        test_y = (old_x, new_y, self.size, self.size)
                        
                        if check_collision(test_x, obstacle.get_rect()):
                            can_move_x = False
                        if check_collision(test_y, obstacle.get_rect()):
                            can_move_y = False
            
            # Apply movement based on collision check
            if can_move_x:
                self.x = new_x
            if can_move_y:
                self.y = new_y
        
        # Shape positions will be updated by camera in game loop
    
    def update_shape_position(self, camera):
        """Update shape position based on camera"""
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        self.shape.x = screen_x
        self.shape.y = screen_y
        self.border.x = screen_x
        self.border.y = screen_y
    
    def get_rect(self):
        return (self.x, self.y, self.size, self.size)

class Rock:
    def __init__(self, x, y, size, batch):
        self.x = x  # World coordinates
        self.y = y
        self.size = size
        self.batch = batch
        self.shape = shapes.Rectangle(0, 0, size, size, color=(100, 100, 100), batch=batch)
        self.border = shapes.Rectangle(0, 0, size, size, color=(150, 150, 150), batch=batch)
        self.border.opacity = 200
    
    def update_shape_position(self, camera):
        """Update shape position based on camera"""
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        self.shape.x = screen_x
        self.shape.y = screen_y
        self.border.x = screen_x
        self.border.y = screen_y
    
    def get_rect(self):
        return (self.x, self.y, self.size, self.size)

class Tree:
    def __init__(self, x, y, batch, tree_id=None):
        self.x = x  # World coordinates
        self.y = y
        self.size = TREE_SIZE
        self.batch = batch
        self.tree_id = tree_id or random.randint(2000, 9999)
        # Brown trunk
        self.trunk = shapes.Rectangle(0, 0, self.size // 3, self.size, color=(139, 69, 19), batch=batch)
        # Green leaves (circle on top)
        self.leaves = shapes.Circle(0, 0, self.size // 2, color=(34, 139, 34), batch=batch)
        self.is_chopped = False
        self.chop_progress = 0.0  # 0.0 to 1.0
        self.current_chop_target = None  # Player currently chopping
    
    def update_shape_position(self, camera):
        """Update shape position based on camera"""
        if self.is_chopped:
            return  # Don't render chopped trees
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        # Center trunk
        self.trunk.x = screen_x - self.size // 6
        self.trunk.y = screen_y - self.size // 2
        # Leaves on top
        self.leaves.x = screen_x
        self.leaves.y = screen_y + self.size // 3
    
    def get_rect(self):
        return (self.x - self.size // 2, self.y - self.size // 2, self.size, self.size)
    
    def update_chop(self, dt):
        """Update chopping progress"""
        if self.current_chop_target and not self.is_chopped:
            self.chop_progress += dt / TREE_CHOP_TIME
            if self.chop_progress >= 1.0:
                self.is_chopped = True
                self.trunk.delete()
                self.leaves.delete()
                return True  # Tree chopped down
        return False

def spawn_enemy(batch, player_x=None, player_y=None):
    # Spawn enemies from the edges of the world or near player
    if player_x is not None and player_y is not None:
        # Spawn enemies near player but outside visible area
        spawn_distance = max(SCREEN_WIDTH, SCREEN_HEIGHT) + 100
        angle = random.uniform(0, 2 * math.pi)
        spawn_x = player_x + math.cos(angle) * spawn_distance
        spawn_y = player_y + math.sin(angle) * spawn_distance
        # Clamp to world bounds
        spawn_x = max(ENEMY_SIZE, min(WORLD_WIDTH - ENEMY_SIZE, spawn_x))
        spawn_y = max(ENEMY_SIZE, min(WORLD_HEIGHT - ENEMY_SIZE, spawn_y))
        return Enemy(spawn_x, spawn_y, batch)
    else:
        # Fallback: spawn at world edges
        side = random.randint(0, 3)
        if side == 0:  # Top
            return Enemy(random.randint(0, WORLD_WIDTH), WORLD_HEIGHT, batch)
        elif side == 1:  # Right
            return Enemy(WORLD_WIDTH, random.randint(0, WORLD_HEIGHT), batch)
        elif side == 2:  # Bottom
            return Enemy(random.randint(0, WORLD_WIDTH), -ENEMY_SIZE, batch)
        else:  # Left
            return Enemy(-ENEMY_SIZE, random.randint(0, WORLD_HEIGHT), batch)

def generate_rocks(batch, num_rocks, exclude_x=None, exclude_y=None, exclude_radius=300):
    """Generate rocks randomly across the world at game start"""
    rocks = []
    attempts = 0
    max_attempts = num_rocks * 20  # Try many times to place rocks
    
    while len(rocks) < num_rocks and attempts < max_attempts:
        attempts += 1
        size = random.randint(ROCK_MIN_SIZE, ROCK_MAX_SIZE)
        x = random.randint(size, WORLD_WIDTH - size)
        y = random.randint(size, WORLD_HEIGHT - size)
        
        # Skip if too close to starting position
        if exclude_x and exclude_y:
            dist = math.sqrt((x - exclude_x)**2 + (y - exclude_y)**2)
            if dist < exclude_radius:
                continue
        
        # Check if this position overlaps with existing rocks
        new_rect = (x, y, size, size)
        overlap = False
        for existing in rocks:
            if check_collision(new_rect, existing.get_rect()):
                overlap = True
                break
        
        if not overlap:
            rocks.append(Rock(x, y, size, batch))
    
    return rocks

def generate_trees(batch, num_trees, exclude_x=None, exclude_y=None, exclude_radius=300, existing_objects=None):
    """Generate trees randomly across the world at game start"""
    trees = []
    attempts = 0
    max_attempts = num_trees * 20
    
    while len(trees) < num_trees and attempts < max_attempts:
        attempts += 1
        x = random.randint(TREE_SIZE, WORLD_WIDTH - TREE_SIZE)
        y = random.randint(TREE_SIZE, WORLD_HEIGHT - TREE_SIZE)
        
        # Skip if too close to starting position
        if exclude_x and exclude_y:
            dist = math.sqrt((x - exclude_x)**2 + (y - exclude_y)**2)
            if dist < exclude_radius:
                continue
        
        # Check if this position overlaps with existing objects
        new_rect = (x - TREE_SIZE // 2, y - TREE_SIZE // 2, TREE_SIZE, TREE_SIZE)
        overlap = False
        
        # Check against existing trees
        for existing in trees:
            if check_collision(new_rect, existing.get_rect()):
                overlap = True
                break
        
        # Check against other objects if provided
        if existing_objects and not overlap:
            for obj in existing_objects:
                if check_collision(new_rect, obj.get_rect()):
                    overlap = True
                    break
        
        if not overlap:
            trees.append(Tree(x, y, batch))
    
    return trees

def check_collision(rect1, rect2):
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2
    return (x1 < x2 + w2 and x1 + w1 > x2 and
            y1 < y2 + h2 and y1 + h1 > y2)

class MenuWindow(pyglet.window.Window):
    def __init__(self):
        super().__init__(width=SCREEN_WIDTH, height=SCREEN_HEIGHT, caption="Cube Shooter Game - Menu")
        self.batch = pyglet.graphics.Batch()
        
        # Menu items
        self.title_label = pyglet.text.Label(
            'CUBE SHOOTER',
            font_name='Arial',
            font_size=48,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 150,
            anchor_x='center', anchor_y='center',
            color=WHITE,
            batch=self.batch
        )
        
        self.single_player_label = pyglet.text.Label(
            '1. Single Player',
            font_name='Arial',
            font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 + 50,
            anchor_x='center', anchor_y='center',
            color=GREEN,
            batch=self.batch
        )
        
        self.multiplayer_label = pyglet.text.Label(
            '2. Multiplayer (Host)',
            font_name='Arial',
            font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2,
            anchor_x='center', anchor_y='center',
            color=CYAN,
            batch=self.batch
        )
        
        self.join_label = pyglet.text.Label(
            '3. Join Game',
            font_name='Arial',
            font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 - 50,
            anchor_x='center', anchor_y='center',
            color=BLUE,
            batch=self.batch
        )
        
        self.instructions_label = pyglet.text.Label(
            'Press 1, 2, or 3 to select',
            font_name='Arial',
            font_size=16,
            x=SCREEN_WIDTH // 2, y=100,
            anchor_x='center', anchor_y='center',
            color=WHITE,
            batch=self.batch
        )
        
        self.connecting_label = None
        self.host_ip_label = None
        
    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.NUM_1 or symbol == pyglet.window.key._1:
            self.start_single_player()
        elif symbol == pyglet.window.key.NUM_2 or symbol == pyglet.window.key._2:
            self.start_host()
        elif symbol == pyglet.window.key.NUM_3 or symbol == pyglet.window.key._3:
            self.start_join()
    
    def start_single_player(self):
        self.close()
        window = GameWindow(is_multiplayer=False)
        pyglet.app.run()
    
    def start_host(self):
        local_ip = get_local_ip()
        print("\n" + "="*50)
        print("HOSTING MULTIPLAYER GAME")
        print("="*50)
        print(f"Your local IP address: {local_ip}")
        print(f"Port: {NETWORK_PORT}")
        print("Waiting for player to connect...")
        print("Share your IP address with your friend!")
        print("="*50 + "\n")
        
        self.close()
        window = GameWindow(is_multiplayer=True, is_host=True)
        pyglet.app.run()
    
    def start_join(self):
        # Simple IP input - you can type in console or modify for GUI input
        import sys
        print("\n" + "="*50)
        print("JOIN MULTIPLAYER GAME")
        print("="*50)
        print("Enter the host's IP address (default: 127.0.0.1 for localhost)")
        host_ip = input("Host IP: ").strip() or "127.0.0.1"
        print(f"Connecting to {host_ip}...")
        print("="*50 + "\n")
        
        self.close()
        window = GameWindow(is_multiplayer=True, is_host=False, host_ip=host_ip)
        pyglet.app.run()
    
    def on_draw(self):
        gl.glClearColor(0, 0, 0, 1)
        self.clear()
        self.batch.draw()

class NetworkManager:
    def __init__(self, is_host=False, host_ip='127.0.0.1'):
        self.is_host = is_host
        self.host_ip = host_ip
        self.port = NETWORK_PORT
        self.socket = None
        self.client_socket = None
        self.connected = False
        self.running = False
        self.receive_thread = None
        self.last_send_time = 0
        self.send_interval = 1.0 / 20  # Reduced to 20 updates per second
        self.received_messages = []  # Thread-safe message queue
        self.receive_lock = threading.Lock()
        self.pending_data = b''  # Buffer for partial messages
        
    def start_host(self):
        """Start hosting a game"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(('0.0.0.0', self.port))
            self.socket.listen(1)
            self.socket.settimeout(1.0)
            self.running = True
            print(f"Hosting on port {self.port}, waiting for connection...")
            return True
        except Exception as e:
            print(f"Error starting host: {e}")
            return False
    
    def accept_client(self):
        """Accept a client connection (host only)"""
        if not self.is_host or not self.socket:
            return False
        try:
            self.client_socket, addr = self.socket.accept()
            self.client_socket.settimeout(0.1)
            self.connected = True
            self.start_receive_thread()
            print(f"Client connected from {addr}")
            return True
        except socket.timeout:
            return False
        except Exception as e:
            print(f"Error accepting client: {e}")
            return False
    
    def connect_to_host(self, host_ip):
        """Connect to a host"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((host_ip, self.port))
            self.socket.settimeout(0.1)
            self.connected = True
            self.running = True
            self.start_receive_thread()
            print(f"Connected to {host_ip}:{self.port}")
            return True
        except Exception as e:
            print(f"Error connecting to host: {e}")
            return False
    
    def send_data(self, data):
        """Send data over network (non-blocking)"""
        if not self.connected:
            return False
        
        current_time = time.time()
        if current_time - self.last_send_time < self.send_interval:
            return False
        
        try:
            socket_to_use = self.client_socket if self.is_host else self.socket
            if socket_to_use:
                # Quick send - should not block significantly
                data_str = json.dumps(data)
                data_bytes = data_str.encode('utf-8')
                length = struct.pack('!I', len(data_bytes))
                socket_to_use.sendall(length + data_bytes)
                self.last_send_time = current_time
                return True
        except socket.error:
            # Would block or connection error - don't spam errors
            self.connected = False
        except Exception:
            # Silently fail to avoid spam
            self.connected = False
        return False
    
    def start_receive_thread(self):
        """Start background thread for receiving"""
        if not self.receive_thread or not self.receive_thread.is_alive():
            self.receive_thread = threading.Thread(target=self._receive_thread, daemon=True)
            self.receive_thread.start()
    
    def receive_data_non_blocking(self):
        """Non-blocking receive - check if data is available"""
        messages = []
        with self.receive_lock:
            if self.received_messages:
                messages = self.received_messages[:]
                self.received_messages.clear()
        return messages
    
    def _receive_thread(self):
        """Background thread for receiving data"""
        while self.running and self.connected:
            try:
                socket_to_use = self.client_socket if self.is_host else self.socket
                if not socket_to_use:
                    time.sleep(0.01)
                    continue
                
                # Try to receive data
                try:
                    chunk = socket_to_use.recv(4096)
                    if not chunk:
                        self.connected = False
                        break
                    self.pending_data += chunk
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"Receive error: {e}")
                    self.connected = False
                    break
                
                # Process complete messages
                while len(self.pending_data) >= 4:
                    length = struct.unpack('!I', self.pending_data[:4])[0]
                    if len(self.pending_data) >= 4 + length:
                        data_bytes = self.pending_data[4:4+length]
                        self.pending_data = self.pending_data[4+length:]
                        try:
                            message = json.loads(data_bytes.decode('utf-8'))
                            with self.receive_lock:
                                self.received_messages.append(message)
                        except:
                            pass
                    else:
                        break
                        
            except Exception as e:
                if self.running:
                    print(f"Thread error: {e}")
                time.sleep(0.01)
    
    def close(self):
        """Close network connections"""
        self.running = False
        self.connected = False
        if self.client_socket:
            self.client_socket.close()
        if self.socket:
            self.socket.close()

class GameWindow(pyglet.window.Window):
    def __init__(self, is_multiplayer=False, is_host=False, host_ip='127.0.0.1'):
        super().__init__(width=SCREEN_WIDTH, height=SCREEN_HEIGHT, caption="Cube Shooter Game")
        self.batch = pyglet.graphics.Batch()
        self.is_multiplayer = is_multiplayer
        self.is_host = is_host
        self.my_player_id = 1 if is_host else 2
        
        # Network setup
        self.network = None
        if is_multiplayer:
            self.network = NetworkManager(is_host=is_host, host_ip=host_ip)
            if is_host:
                if not self.network.start_host():
                    print("Failed to start hosting")
                    self.close()
                    return
            else:
                if not self.network.connect_to_host(host_ip):
                    print(f"Failed to connect to {host_ip}")
                    self.close()
                    return
        
        # Initialize camera
        self.camera = Camera()
        
        # Initialize players (in world coordinates)
        # Note: Sprite positions will be set after camera is initialized
        if is_multiplayer:
            if is_host:
                self.player = Player(WORLD_WIDTH // 4, WORLD_HEIGHT // 2, self.batch, GREEN, 1)
                self.other_player = Player(3 * WORLD_WIDTH // 4, WORLD_HEIGHT // 2, self.batch, CYAN, 2)
            else:
                self.player = Player(3 * WORLD_WIDTH // 4, WORLD_HEIGHT // 2, self.batch, CYAN, 2)
                self.other_player = Player(WORLD_WIDTH // 4, WORLD_HEIGHT // 2, self.batch, GREEN, 1)
        else:
            self.player = Player(WORLD_WIDTH // 2, WORLD_HEIGHT // 2, self.batch, GREEN, 1)
            self.other_player = None
        
        self.projectiles = []
        self.enemies = []
        self.frame_count = 0
        
        # Generate rocks and trees at game start
        player_start_x = self.player.x if self.player else WORLD_WIDTH // 2
        player_start_y = self.player.y if self.player else WORLD_HEIGHT // 2
        self.rocks = generate_rocks(self.batch, MAX_ROCKS, 
                                     exclude_x=player_start_x, 
                                     exclude_y=player_start_y,
                                     exclude_radius=250)
        self.trees = generate_trees(self.batch, MAX_TREES,
                                     exclude_x=player_start_x,
                                     exclude_y=player_start_y,
                                     exclude_radius=250,
                                     existing_objects=self.rocks)
        
        # Immediately position all trees (so they're visible from start)
        for tree in self.trees:
            tree.update_shape_position(self.camera)
        
        # Enemy spawning (only host spawns enemies in multiplayer)
        self.enemy_spawn_rate = INITIAL_ENEMY_SPAWN_RATE
        self.enemy_spawn_counter = 0
        self.enemy_spawn_timer = 0.0  # Initialize timer
        self.game_time = 0.0
        
        # Track mouse position
        self.mouse_x = SCREEN_WIDTH // 2
        self.mouse_y = SCREEN_HEIGHT // 2
        
        # Track pressed keys
        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)
        
        # Labels
        self.score_label = pyglet.text.Label(
            'Enemies: 0',
            font_name='Arial',
            font_size=16,
            x=10, y=SCREEN_HEIGHT - 25,
            color=WHITE,
            batch=self.batch
        )
        
        self.wood_label = pyglet.text.Label(
            'Wood: 0',
            font_name='Arial',
            font_size=16,
            x=10, y=SCREEN_HEIGHT - 45,
            color=WHITE,
            batch=self.batch
        )
        
        if is_multiplayer:
            self.connection_label = pyglet.text.Label(
                'Connected' if self.network and self.network.connected else 'Connecting...',
                font_name='Arial',
                font_size=14,
                x=10, y=SCREEN_HEIGHT - 65,
                color=GREEN if (self.network and self.network.connected) else YELLOW,
                batch=self.batch
            )
        
        # Initialize sprite positions immediately
        if self.player:
            player_center_x, player_center_y = self.player.get_center()
            self.camera.update(player_center_x, player_center_y)
            self.player.update_sprite_position(self.camera)
        if self.other_player:
            self.other_player.update_sprite_position(self.camera)
        
        # Schedule update
        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)
        
        # Accept client connection if hosting
        if is_multiplayer and is_host:
            pyglet.clock.schedule_once(lambda dt: self.check_connection(), 0.1)
    
    def check_connection(self):
        """Check for client connection (host only)"""
        if self.network and not self.network.connected:
            if self.network.accept_client():
                if self.connection_label:
                    self.connection_label.text = 'Connected'
                    self.connection_label.color = GREEN
            pyglet.clock.schedule_once(lambda dt: self.check_connection(), 0.1)
    
    def on_key_press(self, symbol, modifiers):
        # Arrow keys fire projectiles in their direction
        direction_x = 0
        direction_y = 0
        
        if symbol == pyglet.window.key.UP:
            direction_y = 1
        elif symbol == pyglet.window.key.DOWN:
            direction_y = -1
        elif symbol == pyglet.window.key.LEFT:
            direction_x = -1
        elif symbol == pyglet.window.key.RIGHT:
            direction_x = 1
        
        # If an arrow key was pressed, shoot a projectile
        if direction_x != 0 or direction_y != 0:
            player_center_x, player_center_y = self.player.get_center()
            direction_x = direction_x * 100
            direction_y = direction_y * 100
            
            projectile = Projectile(
                player_center_x - PROJECTILE_SIZE / 2,
                player_center_y - PROJECTILE_SIZE / 2,
                direction_x,
                direction_y,
                self.batch,
                owner_id=self.my_player_id,
                player_velocity_x=self.player.velocity_x,
                player_velocity_y=self.player.velocity_y
            )
            self.projectiles.append(projectile)
    
    def update(self, dt):
        self.frame_count += 1
        self.game_time += dt
        
        # Update camera to follow player
        player_center_x, player_center_y = self.player.get_center()
        self.camera.update(player_center_x, player_center_y)
        
        # Update sprite positions immediately after camera update
        
        # Handle networking (optimized - only when multiplayer)
        if self.is_multiplayer and self.network and self.network.connected:
            # Send player data (throttled by send_interval)
            player_data = self.player.to_dict()
            self.network.send_data({
                'type': 'player_update',
                'player': player_data
            })
            
            # Send new projectiles (only send once when created)
            for proj in self.projectiles:
                if proj.owner_id == self.my_player_id and not hasattr(proj, 'network_sent'):
                    # Normalize direction vector for transmission
                    norm_dx = proj.dx / PROJECTILE_SPEED if PROJECTILE_SPEED > 0 else 0
                    norm_dy = proj.dy / PROJECTILE_SPEED if PROJECTILE_SPEED > 0 else 0
                    self.network.send_data({
                        'type': 'projectile',
                        'x': proj.x,
                        'y': proj.y,
                        'dx': norm_dx,
                        'dy': norm_dy,
                        'owner_id': self.my_player_id
                    })
                    proj.network_sent = True
            
            # Receive data (non-blocking, from queue)
            messages = self.network.receive_data_non_blocking()
            for data in messages:
                if data.get('type') == 'player_update':
                    other_data = data.get('player', {})
                    if self.other_player and other_data.get('id') == self.other_player.player_id:
                        self.other_player.update_position(other_data['x'], other_data['y'])
                elif data.get('type') == 'projectile':
                    if data.get('owner_id') != self.my_player_id:
                        # Scale direction vector back to full speed
                        dx = data['dx'] * PROJECTILE_SPEED
                        dy = data['dy'] * PROJECTILE_SPEED
                        proj = Projectile(
                            data['x'], data['y'],
                            dx, dy,
                            self.batch, owner_id=data['owner_id']
                        )
                        proj.network_sent = True  # Mark as received from network
                        self.projectiles.append(proj)
                elif data.get('type') == 'enemy_spawn' and not self.is_host:
                    # Client receives enemy spawn from host
                    enemy = Enemy(data['x'], data['y'], self.batch, data.get('id'))
                    self.enemies.append(enemy)
        
        # Update player (pass rocks and trees for collision checking)
        self.player.update(self.keys, dt, rocks=self.rocks, trees=self.trees)
        
        # Update player sprite position (camera-based)
        self.player.update_sprite_position(self.camera)
        
        # Update other player sprite if multiplayer
        if self.other_player:
            self.other_player.update_sprite_position(self.camera)
        
        # Handle interaction (spacebar)
        interact_key_pressed = self.keys[pyglet.window.key.SPACE]
        nearby_tree = None
        
        if interact_key_pressed and self.player:
            player_rect = self.player.get_rect()
            # Check if player is near a tree
            for tree in self.trees:
                if not tree.is_chopped and check_collision(player_rect, tree.get_rect()):
                    nearby_tree = tree
                    break
        
        # Update tree chopping
        for tree in self.trees:
            if tree == nearby_tree and interact_key_pressed:
                tree.current_chop_target = self.player
                if tree.update_chop(dt):
                    # Tree chopped down
                    self.player.wood += 1
                    self.trees.remove(tree)
            else:
                tree.current_chop_target = None
                tree.chop_progress = 0.0
        
        # Update projectiles
        self.projectiles = [p for p in self.projectiles if not p.is_off_world()]
        for projectile in self.projectiles:
            projectile.update()
            projectile.update_shape_position(self.camera)
        
        # Enemy spawning (only host in multiplayer) - time-based for consistent spawn rate
        if not self.is_multiplayer or (self.is_host and self.network and self.network.connected):
            # Convert frame-based spawn rate to time-based
            # Lower spawn_rate = faster spawning (every N frames)
            # We'll use a time accumulator instead
            if not hasattr(self, 'enemy_spawn_timer'):
                self.enemy_spawn_timer = 0.0
            
            # Calculate target spawn interval in seconds
            frames_per_spawn = INITIAL_ENEMY_SPAWN_RATE - (self.game_time * ENEMY_SPAWN_ACCELERATION)
            frames_per_spawn = max(MIN_ENEMY_SPAWN_RATE, frames_per_spawn)
            spawn_interval = frames_per_spawn / FPS  # Convert frames to seconds
            
            self.enemy_spawn_timer += dt
            if len(self.enemies) < MAX_ENEMIES and self.enemy_spawn_timer >= spawn_interval:
                enemy = spawn_enemy(self.batch, player_center_x, player_center_y)
                self.enemies.append(enemy)
                # Immediately position enemy sprite
                enemy.update_shape_position(self.camera)
                self.enemy_spawn_timer = 0.0
                
                # Send enemy spawn to client
                if self.is_multiplayer and self.network and self.network.connected:
                    self.network.send_data({
                        'type': 'enemy_spawn',
                        'x': enemy.x,
                        'y': enemy.y,
                        'id': enemy.enemy_id
                    })
        
        # Update enemies (chase closest player) - pass dt for time-based movement
        # Pass all obstacles (rocks and non-chopped trees) for collision
        all_obstacles = list(self.rocks) + [t for t in self.trees if not t.is_chopped]
        for enemy in self.enemies:
            enemy.update(player_center_x, player_center_y, dt, rocks=all_obstacles)
            enemy.update_shape_position(self.camera)
        
        # Update rock positions
        for rock in self.rocks:
            rock.update_shape_position(self.camera)
        
        # Update tree positions
        for tree in self.trees:
            tree.update_shape_position(self.camera)
        
        # Collision detection
        enemies_to_remove = []
        projectiles_to_remove = []
        
        # Projectiles vs enemies
        for enemy in self.enemies:
            for projectile in self.projectiles:
                if check_collision(enemy.get_rect(), projectile.get_rect()):
                    if enemy not in enemies_to_remove:
                        enemies_to_remove.append(enemy)
                    if projectile not in projectiles_to_remove:
                        projectiles_to_remove.append(projectile)
        
        # Projectiles vs rocks
        for rock in self.rocks:
            for projectile in self.projectiles:
                if check_collision(rock.get_rect(), projectile.get_rect()):
                    if projectile not in projectiles_to_remove:
                        projectiles_to_remove.append(projectile)
        
        # Projectiles vs trees
        for tree in self.trees:
            if not tree.is_chopped:
                for projectile in self.projectiles:
                    if check_collision(tree.get_rect(), projectile.get_rect()):
                        if projectile not in projectiles_to_remove:
                            projectiles_to_remove.append(projectile)
        
        # Player vs rocks collision is now handled in player.update() method
        
        # Remove collided objects
        for enemy in enemies_to_remove:
            enemy.shape.delete()
            enemy.border.delete()
            self.enemies.remove(enemy)
        for projectile in projectiles_to_remove:
            projectile.shape.delete()
            self.projectiles.remove(projectile)
        
        # Check if player is hit by enemy
        if self.player:
            player_rect = self.player.get_rect()
            for enemy in self.enemies:
                if check_collision(player_rect, enemy.get_rect()):
                    self.close()
                    return
        
        # Update score label
        self.score_label.text = f"Enemies: {len(self.enemies)}"
        
        # Update wood label
        self.wood_label.text = f"Wood: {self.player.wood}"
    
    def on_draw(self):
        gl.glClearColor(0, 0, 0, 1)
        self.clear()
        self.batch.draw()
    
    def on_close(self):
        if self.network:
            self.network.close()
        super().on_close()

def get_local_ip():
    """Get local IP address for hosting"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def main():
    # Show menu first
    menu = MenuWindow()
    pyglet.app.run()

if __name__ == "__main__":
    main()
