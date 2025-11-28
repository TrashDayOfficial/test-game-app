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
PLAYER_SPEED = 5
SPRINT_SPEED_MULTIPLIER = 2.0  # Sprint is 2x speed
SPRINT_MAX = 100.0  # Maximum sprint energy
SPRINT_DEPLETION_RATE = 30.0  # Energy lost per second while sprinting
SPRINT_RECHARGE_RATE = 20.0  # Energy gained per second when not sprinting

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

class Player:
    def __init__(self, x, y, batch, color=GREEN, player_id=1):
        self.x = x
        self.y = y
        self.size = PLAYER_SIZE
        self.speed = PLAYER_SPEED
        self.batch = batch
        self.player_id = player_id
        # Sprint system
        self.sprint_energy = SPRINT_MAX  # Start with full sprint
        self.is_sprinting = False
        # Track last movement direction for shooting
        self.last_direction_x = 0
        self.last_direction_y = 1  # Default: facing up
        # Create a solid color image for the player sprite
        format = 'RGBA'
        pitch = self.size * len(format)
        data = bytes(color + (255,)) * (self.size * self.size)  # RGBA bytes
        self.image = pyglet.image.ImageData(self.size, self.size, format, data, pitch=-pitch)
        self.sprite = pyglet.sprite.Sprite(self.image, x=x, y=y, batch=batch)
        self.sprite.visible = True
        
    def update(self, keys, dt):
        # Check if sprinting (spacebar held)
        self.is_sprinting = keys[pyglet.window.key.SPACE] and self.sprint_energy > 0
        
        # Update sprint energy
        if self.is_sprinting:
            self.sprint_energy -= SPRINT_DEPLETION_RATE * dt
            self.sprint_energy = max(0, self.sprint_energy)
        else:
            self.sprint_energy += SPRINT_RECHARGE_RATE * dt
            self.sprint_energy = min(SPRINT_MAX, self.sprint_energy)
        
        # Calculate current speed (sprint multiplier if sprinting and has energy)
        current_speed = self.speed
        if self.is_sprinting and self.sprint_energy > 0:
            current_speed = self.speed * SPRINT_SPEED_MULTIPLIER
        
        # Track movement direction
        move_x = 0
        move_y = 0
        
        # Movement (using KeyStateHandler)
        if keys[pyglet.window.key.W] or keys[pyglet.window.key.UP]:
            self.y += current_speed
            move_y += 1
        if keys[pyglet.window.key.S] or keys[pyglet.window.key.DOWN]:
            self.y -= current_speed
            move_y -= 1
        if keys[pyglet.window.key.A] or keys[pyglet.window.key.LEFT]:
            self.x -= current_speed
            move_x -= 1
        if keys[pyglet.window.key.D] or keys[pyglet.window.key.RIGHT]:
            self.x += current_speed
            move_x += 1
        
        # Update last direction if moving
        if move_x != 0 or move_y != 0:
            self.last_direction_x = move_x
            self.last_direction_y = move_y
        
        # Keep player on screen
        self.x = max(0, min(SCREEN_WIDTH - self.size, self.x))
        self.y = max(0, min(SCREEN_HEIGHT - self.size, self.y))
        
        # Update sprite position
        self.sprite.x = self.x
        self.sprite.y = self.y
    
    def update_position(self, x, y):
        """Update position from network (for multiplayer)"""
        self.x = x
        self.y = y
        self.sprite.x = self.x
        self.sprite.y = self.y
    
    def get_sprint_percentage(self):
        """Return sprint energy as a percentage (0.0 to 1.0)"""
        return self.sprint_energy / SPRINT_MAX
    
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
            'y': self.y,
            'sprint_energy': self.sprint_energy
        }

class Projectile:
    def __init__(self, x, y, direction_x, direction_y, batch, owner_id=1):
        self.x = x
        self.y = y
        self.size = PROJECTILE_SIZE
        self.speed = PROJECTILE_SPEED
        self.owner_id = owner_id
        # Normalize direction
        length = math.sqrt(direction_x**2 + direction_y**2)
        if length > 0:
            self.dx = (direction_x / length) * self.speed
            self.dy = (direction_y / length) * self.speed
        else:
            self.dx = 0
            self.dy = self.speed  # Default: shoot up
        self.batch = batch
        self.shape = shapes.Circle(x + self.size/2, y + self.size/2, self.size // 2, color=YELLOW, batch=batch)
    
    def update(self):
        self.x += self.dx
        self.y += self.dy
        self.shape.x = self.x + self.size/2
        self.shape.y = self.y + self.size/2
    
    def is_off_screen(self):
        return (self.x < -self.size or self.x > SCREEN_WIDTH or 
                self.y < -self.size or self.y > SCREEN_HEIGHT)
    
    def get_rect(self):
        return (self.x, self.y, self.size, self.size)

class Enemy:
    def __init__(self, x, y, batch, enemy_id=None):
        self.x = x
        self.y = y
        self.size = ENEMY_SIZE
        self.speed = ENEMY_SPEED
        self.batch = batch
        self.enemy_id = enemy_id or random.randint(1000, 9999)
        self.shape = shapes.Rectangle(x, y, self.size, self.size, color=RED, batch=batch)
        self.border = shapes.Rectangle(x, y, self.size, self.size, color=WHITE, batch=batch)
        self.border.opacity = 128  # Make border semi-transparent
    
    def update(self, player_x, player_y):
        # Chase the player
        dx = player_x - self.x
        dy = player_y - self.y
        distance = math.sqrt(dx**2 + dy**2)
        
        if distance > 0:
            # Normalize and apply speed
            self.x += (dx / distance) * self.speed
            self.y += (dy / distance) * self.speed
        
        # Update shape positions
        self.shape.x = self.x
        self.shape.y = self.y
        self.border.x = self.x
        self.border.y = self.y
    
    def get_rect(self):
        return (self.x, self.y, self.size, self.size)

def spawn_enemy(batch):
    # Spawn enemies from the edges of the screen
    side = random.randint(0, 3)
    if side == 0:  # Top
        return Enemy(random.randint(0, SCREEN_WIDTH), SCREEN_HEIGHT, batch)
    elif side == 1:  # Right
        return Enemy(SCREEN_WIDTH, random.randint(0, SCREEN_HEIGHT), batch)
    elif side == 2:  # Bottom
        return Enemy(random.randint(0, SCREEN_WIDTH), -ENEMY_SIZE, batch)
    else:  # Left
        return Enemy(-ENEMY_SIZE, random.randint(0, SCREEN_HEIGHT), batch)

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
        self.send_interval = 1.0 / 30  # 30 updates per second
        
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
            print(f"Connected to {host_ip}:{self.port}")
            return True
        except Exception as e:
            print(f"Error connecting to host: {e}")
            return False
    
    def send_data(self, data):
        """Send data over network"""
        if not self.connected:
            return False
        
        current_time = time.time()
        if current_time - self.last_send_time < self.send_interval:
            return False
        
        try:
            socket_to_use = self.client_socket if self.is_host else self.socket
            if socket_to_use:
                data_str = json.dumps(data)
                data_bytes = data_str.encode('utf-8')
                length = struct.pack('!I', len(data_bytes))
                socket_to_use.sendall(length + data_bytes)
                self.last_send_time = current_time
                return True
        except Exception as e:
            print(f"Error sending data: {e}")
            self.connected = False
        return False
    
    def receive_data(self):
        """Receive data from network"""
        if not self.connected:
            return None
        
        try:
            socket_to_use = self.client_socket if self.is_host else self.socket
            if socket_to_use:
                # Receive length
                length_data = socket_to_use.recv(4)
                if len(length_data) < 4:
                    return None
                length = struct.unpack('!I', length_data)[0]
                
                # Receive data
                data = b''
                while len(data) < length:
                    chunk = socket_to_use.recv(length - len(data))
                    if not chunk:
                        return None
                    data += chunk
                
                return json.loads(data.decode('utf-8'))
        except socket.timeout:
            return None
        except Exception as e:
            print(f"Error receiving data: {e}")
            self.connected = False
        return None
    
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
        
        # Initialize players
        if is_multiplayer:
            if is_host:
                self.player = Player(SCREEN_WIDTH // 4, SCREEN_HEIGHT // 2, self.batch, GREEN, 1)
                self.other_player = Player(3 * SCREEN_WIDTH // 4, SCREEN_HEIGHT // 2, self.batch, CYAN, 2)
            else:
                self.player = Player(3 * SCREEN_WIDTH // 4, SCREEN_HEIGHT // 2, self.batch, CYAN, 2)
                self.other_player = Player(SCREEN_WIDTH // 4, SCREEN_HEIGHT // 2, self.batch, GREEN, 1)
        else:
            self.player = Player(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, self.batch, GREEN, 1)
            self.other_player = None
        
        self.projectiles = []
        self.enemies = []
        self.frame_count = 0
        
        # Enemy spawning (only host spawns enemies in multiplayer)
        self.enemy_spawn_rate = INITIAL_ENEMY_SPAWN_RATE
        self.enemy_spawn_counter = 0
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
        
        if is_multiplayer:
            self.connection_label = pyglet.text.Label(
                'Connected' if self.network and self.network.connected else 'Connecting...',
                font_name='Arial',
                font_size=14,
                x=10, y=SCREEN_HEIGHT - 45,
                color=GREEN if (self.network and self.network.connected) else YELLOW,
                batch=self.batch
            )
        
        # Sprint bar
        self.sprint_bar_bg = shapes.Rectangle(
            10, 10, 200, 15, color=(50, 50, 50), batch=self.batch
        )
        self.sprint_bar_fill = shapes.Rectangle(
            12, 12, 196, 11, color=(0, 200, 255), batch=self.batch
        )
        self.sprint_label = pyglet.text.Label(
            'Sprint',
            font_name='Arial',
            font_size=12,
            x=10, y=30,
            color=WHITE,
            batch=self.batch
        )
        
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
                owner_id=self.my_player_id
            )
            self.projectiles.append(projectile)
    
    def update(self, dt):
        self.frame_count += 1
        self.game_time += dt
        
        # Handle networking
        if self.is_multiplayer and self.network:
            # Send player data
            if self.network.connected:
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
                
                # Receive data
                data = self.network.receive_data()
                if data:
                    if data.get('type') == 'player_update':
                        other_data = data.get('player', {})
                        if self.other_player and other_data.get('id') == self.other_player.player_id:
                            self.other_player.update_position(other_data['x'], other_data['y'])
                            self.other_player.sprint_energy = other_data.get('sprint_energy', SPRINT_MAX)
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
        
        # Update player
        self.player.update(self.keys, dt)
        
        # Update sprint bar
        sprint_percent = self.player.get_sprint_percentage()
        self.sprint_bar_fill.width = 196 * sprint_percent
        
        # Update projectiles
        self.projectiles = [p for p in self.projectiles if not p.is_off_screen()]
        for projectile in self.projectiles:
            projectile.update()
        
        # Enemy spawning (only host in multiplayer)
        if not self.is_multiplayer or (self.is_host and self.network and self.network.connected):
            new_spawn_rate = INITIAL_ENEMY_SPAWN_RATE - (self.game_time * ENEMY_SPAWN_ACCELERATION)
            self.enemy_spawn_rate = max(MIN_ENEMY_SPAWN_RATE, new_spawn_rate)
            
            self.enemy_spawn_counter += 1
            if len(self.enemies) < MAX_ENEMIES and self.enemy_spawn_counter >= self.enemy_spawn_rate:
                enemy = spawn_enemy(self.batch)
                self.enemies.append(enemy)
                self.enemy_spawn_counter = 0
                
                # Send enemy spawn to client
                if self.is_multiplayer and self.network and self.network.connected:
                    self.network.send_data({
                        'type': 'enemy_spawn',
                        'x': enemy.x,
                        'y': enemy.y,
                        'id': enemy.enemy_id
                    })
        
        # Update enemies (chase closest player)
        if self.player:
            player_center_x, player_center_y = self.player.get_center()
            for enemy in self.enemies:
                enemy.update(player_center_x, player_center_y)
        
        # Collision detection
        enemies_to_remove = []
        projectiles_to_remove = []
        
        for enemy in self.enemies:
            for projectile in self.projectiles:
                if check_collision(enemy.get_rect(), projectile.get_rect()):
                    if enemy not in enemies_to_remove:
                        enemies_to_remove.append(enemy)
                    if projectile not in projectiles_to_remove:
                        projectiles_to_remove.append(projectile)
        
        # Remove collided objects
        for enemy in enemies_to_remove:
            enemy.shape.delete()
            enemy.border.delete()
            self.enemies.remove(enemy)
        for projectile in projectiles_to_remove:
            projectile.shape.delete()
            self.projectiles.remove(projectile)
        
        # Check if player is hit
        if self.player:
            player_rect = self.player.get_rect()
            for enemy in self.enemies:
                if check_collision(player_rect, enemy.get_rect()):
                    self.close()
                    return
        
        # Update score label
        self.score_label.text = f"Enemies: {len(self.enemies)}"
    
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
