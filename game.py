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

# Projectile settings
PROJECTILE_SIZE = 10
PROJECTILE_SPEED = 10

# Enemy settings
ENEMY_SIZE = 25
ENEMY_SPEED = 2
ENEMY_SPAWN_RATE = 60  # Spawns every N frames
MAX_ENEMIES = 10

class Player:
    def __init__(self, x, y, batch):
        self.x = x
        self.y = y
        self.size = PLAYER_SIZE
        self.speed = PLAYER_SPEED
        self.batch = batch
        # Create a solid color image for the player sprite (more reliable than shapes)
        # Create image data with solid green color (RGBA format: 0x00FF00FF = green opaque)
        format = 'RGBA'
        pitch = self.size * len(format)
        data = bytes(GREEN + (255,)) * (self.size * self.size)  # RGBA bytes
        self.image = pyglet.image.ImageData(self.size, self.size, format, data, pitch=-pitch)
        self.sprite = pyglet.sprite.Sprite(self.image, x=x, y=y, batch=batch)
        self.sprite.visible = True
        
    def update(self, keys):
        # Movement (using KeyStateHandler)
        if keys[pyglet.window.key.W] or keys[pyglet.window.key.UP]:
            self.y += self.speed
        if keys[pyglet.window.key.S] or keys[pyglet.window.key.DOWN]:
            self.y -= self.speed
        if keys[pyglet.window.key.A] or keys[pyglet.window.key.LEFT]:
            self.x -= self.speed
        if keys[pyglet.window.key.D] or keys[pyglet.window.key.RIGHT]:
            self.x += self.speed
        
        # Keep player on screen
        self.x = max(0, min(SCREEN_WIDTH - self.size, self.x))
        self.y = max(0, min(SCREEN_HEIGHT - self.size, self.y))
        
        # Update sprite position
        self.sprite.x = self.x
        self.sprite.y = self.y
    
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
        
        # Note: We don't need a background rectangle since we clear to black in on_draw()
        
        # Schedule update
        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)
    
    def on_mouse_motion(self, x, y, dx, dy):
        # Track mouse position (pyglet coordinate system: y is from bottom)
        self.mouse_x = x
        self.mouse_y = SCREEN_HEIGHT - y  # Convert to bottom-left origin
    
    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.SPACE:
            # Shoot projectile towards mouse position
            player_center_x, player_center_y = self.player.get_center()
            direction_x = self.mouse_x - player_center_x
            direction_y = self.mouse_y - player_center_y
            
            # Default direction if mouse is at player center (shoot up)
            if abs(direction_x) < 0.1 and abs(direction_y) < 0.1:
                direction_x = 0
                direction_y = 100
            
            self.projectiles.append(Projectile(
                player_center_x - PROJECTILE_SIZE / 2,
                player_center_y - PROJECTILE_SIZE / 2,
                direction_x,
                direction_y,
                self.batch
            ))
    
    def update(self, dt):
        self.frame_count += 1
        
        # Update player with current key states
        self.player.update(self.keys)
        
        # Update projectiles
        self.projectiles = [p for p in self.projectiles if not p.is_off_screen()]
        for projectile in self.projectiles:
            projectile.update()
        
        # Spawn enemies
        if len(self.enemies) < MAX_ENEMIES and self.frame_count % ENEMY_SPAWN_RATE == 0:
            self.enemies.append(spawn_enemy(self.batch))
        
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
