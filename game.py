import pyglet
from pyglet import shapes
from pyglet import gl
import random
import math

# Constants
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60

# Colors (RGB for pyglet shapes)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)  # Bright green for player (very visible on black)
CYAN = (0, 255, 255)  # Bright cyan
BLUE = (100, 150, 255)
YELLOW = (255, 255, 0)

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
    def __init__(self, x, y, batch):
        self.x = x
        self.y = y
        self.size = PLAYER_SIZE
        self.speed = PLAYER_SPEED
        self.batch = batch
        # Sprint system
        self.sprint_energy = SPRINT_MAX  # Start with full sprint
        self.is_sprinting = False
        # Track last movement direction for shooting
        self.last_direction_x = 0
        self.last_direction_y = 1  # Default: facing up
        # Create a solid color image for the player sprite (more reliable than shapes)
        # Create image data with solid green color (RGBA format: 0x00FF00FF = green opaque)
        format = 'RGBA'
        pitch = self.size * len(format)
        data = bytes(GREEN + (255,)) * (self.size * self.size)  # RGBA bytes
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

class Projectile:
    def __init__(self, x, y, direction_x, direction_y, batch):
        self.x = x
        self.y = y
        self.size = PROJECTILE_SIZE
        self.speed = PROJECTILE_SPEED
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
    def __init__(self, x, y, batch):
        self.x = x
        self.y = y
        self.size = ENEMY_SIZE
        self.speed = ENEMY_SPEED
        self.batch = batch
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

class GameWindow(pyglet.window.Window):
    def __init__(self):
        super().__init__(width=SCREEN_WIDTH, height=SCREEN_HEIGHT, caption="Cube Shooter Game")
        self.batch = pyglet.graphics.Batch()
        
        # Initialize game objects
        self.player = Player(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, self.batch)
        self.projectiles = []
        self.enemies = []
        self.frame_count = 0
        
        # Enemy spawning
        self.enemy_spawn_rate = INITIAL_ENEMY_SPAWN_RATE
        self.enemy_spawn_counter = 0
        self.game_time = 0.0  # Track game time in seconds
        
        # Track mouse position (no longer used for shooting, but kept for compatibility)
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
        
        # Note: We don't need a background rectangle since we clear to black in on_draw()
        
        # Schedule update
        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)
    
    def on_mouse_motion(self, x, y, dx, dy):
        # Track mouse position (pyglet coordinate system: y is from bottom)
        self.mouse_x = x
        self.mouse_y = SCREEN_HEIGHT - y  # Convert to bottom-left origin
    
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
            # Scale direction for shooting
            direction_x = direction_x * 100
            direction_y = direction_y * 100
            
            self.projectiles.append(Projectile(
                player_center_x - PROJECTILE_SIZE / 2,
                player_center_y - PROJECTILE_SIZE / 2,
                direction_x,
                direction_y,
                self.batch
            ))
    
    def update(self, dt):
        self.frame_count += 1
        self.game_time += dt
        
        # Update player with current key states (pass dt for sprint recharge)
        self.player.update(self.keys, dt)
        
        # Update sprint bar display
        sprint_percent = self.player.get_sprint_percentage()
        self.sprint_bar_fill.width = 196 * sprint_percent
        
        # Update projectiles
        self.projectiles = [p for p in self.projectiles if not p.is_off_screen()]
        for projectile in self.projectiles:
            projectile.update()
        
        # Gradually increase enemy spawn rate over time
        # Lower spawn_rate = faster spawning
        new_spawn_rate = INITIAL_ENEMY_SPAWN_RATE - (self.game_time * ENEMY_SPAWN_ACCELERATION)
        self.enemy_spawn_rate = max(MIN_ENEMY_SPAWN_RATE, new_spawn_rate)
        
        # Spawn enemies based on current spawn rate
        self.enemy_spawn_counter += 1
        if len(self.enemies) < MAX_ENEMIES and self.enemy_spawn_counter >= self.enemy_spawn_rate:
            self.enemies.append(spawn_enemy(self.batch))
            self.enemy_spawn_counter = 0
        
        # Update enemies
        player_center_x, player_center_y = self.player.get_center()
        for enemy in self.enemies:
            enemy.update(player_center_x, player_center_y)
        
        # Collision detection: projectiles vs enemies
        enemies_to_remove = []
        projectiles_to_remove = []
        
        for enemy in self.enemies:
            for projectile in self.projectiles:
                if check_collision(enemy.get_rect(), projectile.get_rect()):
                    if enemy not in enemies_to_remove:
                        enemies_to_remove.append(enemy)
                    if projectile not in projectiles_to_remove:
                        projectiles_to_remove.append(projectile)
        
        # Remove collided enemies and projectiles
        for enemy in enemies_to_remove:
            enemy.shape.delete()
            enemy.border.delete()
            self.enemies.remove(enemy)
        for projectile in projectiles_to_remove:
            projectile.shape.delete()
            self.projectiles.remove(projectile)
        
        # Check if player is hit by enemy
        player_rect = self.player.get_rect()
        for enemy in self.enemies:
            if check_collision(player_rect, enemy.get_rect()):
                self.close()
                return
        
        # Update score label
        self.score_label.text = f"Enemies: {len(self.enemies)}"
    
    def on_draw(self):
        # Clear window with black background
        gl.glClearColor(0, 0, 0, 1)  # Black background
        self.clear()
        
        # Draw all shapes in batch
        self.batch.draw()

def main():
    window = GameWindow()
    pyglet.app.run()

if __name__ == "__main__":
    main()
