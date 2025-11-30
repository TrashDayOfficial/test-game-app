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

# Global screen manager - holds the current active window
class ScreenManager:
    """Manages window transitions without multiple pyglet.app.run() calls"""
    current_window = None
    
    @classmethod
    def set_window(cls, window):
        """Set the current window, closing the previous one if it exists"""
        if cls.current_window is not None and cls.current_window != window:
            try:
                cls.current_window.close()
            except:
                pass
        cls.current_window = window
    
    @classmethod
    def get_window(cls):
        return cls.current_window

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
PLAYER_HITBOX_MARGIN = 4  # Pixels smaller than visual size for smoother movement through gaps
PLAYER_SPEED = 150
PLAYER_MAX_HEALTH = 100
PLAYER_HEALTH_REGEN_RATE = .05  # Health regen per second
PLAYER_HEALTH_REGEN_DELAY = 10.0  # Delay before health regen starts
PLAYER_HEALTH_REGEN_INTERVAL = 0.5  # Interval between health regen
# Pixels per second (time-based movement)

# Corner sliding threshold - how close to a gap before we auto-align
CORNER_SLIDE_THRESHOLD = 8  # pixels

# Projectile settings
PROJECTILE_SIZE = 10
PROJECTILE_SPEED = 10
PROJECTILE_FIRE_RATE = .5  # Seconds between shots (2 shots per second)

# Enemy settings
ENEMY_SIZE = 25
ENEMY_SPEED = 2
INITIAL_ENEMY_SPAWN_RATE = 60  # Initial spawn rate (spawns every N frames)
MIN_ENEMY_SPAWN_RATE = 10  # Minimum spawn rate (fastest spawning)
MAX_ENEMIES = 150
ENEMY_SPAWN_ACCELERATION = 0.5  # How fast spawn rate decreases (frames per second)
ENEMY_PATHFINDING_RANGE = 50  # Distance to check for obstacles when pathfinding

# Day/Night cycle settings
DAY_LENGTH = 60.0  # Day duration in seconds (60 = 1 minute)
NIGHT_LENGTH = 45.0  # Night duration in seconds
NIGHT_SPAWN_MULTIPLIER_BASE = 1.5  # Base spawn rate multiplier at night
NIGHT_SPAWN_MULTIPLIER_PER_DAY = 0.3  # Additional spawn multiplier per day survived
NIGHT_MAX_ENEMIES_BASE = 30  # Base max enemies at night
NIGHT_MAX_ENEMIES_PER_DAY = 10  # Additional max enemies per day survived

# Rock settings
ROCK_MIN_SIZE = 40
ROCK_MAX_SIZE = 120
MAX_ROCKS = 50  # Generate this many rocks at game start

# Tree settings
TREE_SIZE = 25  # Smaller than rocks
MAX_TREES = 80  # Generate this many trees at game start
TREE_CHOP_TIME = 1.5  # Time in seconds to chop down a tree
HARVEST_RANGE = 60
  # Distance from player center to tree center for harvesting (pixels)

# Wall/Building settings
WALL_WOOD_COST = 1  # Wood required to build a wall

# Grid system settings (snap everything to character-sized cubes)
GRID_SIZE = PLAYER_SIZE  # Grid cells are player-sized
WALL_SIZE = GRID_SIZE  # Walls are same size as grid cells for uniformity

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
        self.coins = 0
        # Create a solid color image for the player sprite
        format = 'RGBA'
        pitch = self.size * len(format)
        data = bytes(color + (255,)) * (self.size * self.size)  # RGBA bytes
        self.image = pyglet.image.ImageData(self.size, self.size, format, data, pitch=-pitch)
        # Initial sprite position (will be updated by camera)
        # Position at center of screen initially
        self.sprite = pyglet.sprite.Sprite(self.image, x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2, batch=batch)
        self.sprite.visible = True
        
    def get_hitbox(self):
        """Return the collision hitbox (slightly smaller than visual for smoother movement)"""
        margin = PLAYER_HITBOX_MARGIN
        return (self.x + margin, self.y + margin, 
                self.size - margin * 2, self.size - margin * 2)
    
    def update(self, keys, dt, rocks=None, trees=None, walls=None):
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
        
        # Use smaller hitbox for collision (allows easier movement through gaps)
        margin = PLAYER_HITBOX_MARGIN
        hitbox_size = self.size - margin * 2
        
        # Check collision with rocks and trees before moving
        player_rect = (new_x + margin, new_y + margin, hitbox_size, hitbox_size)
        can_move_x = True
        can_move_y = True
        
        # Check collision with all obstacles (rocks, trees, and solid walls)
        obstacles_to_check = []
        if rocks:
            obstacles_to_check.extend(rocks)
        if trees:
            # Only check collision with non-chopped trees
            obstacles_to_check.extend([t for t in trees if not t.is_chopped])
        if walls:
            # Only check collision with solid walls (ones that are active)
            obstacles_to_check.extend([w for w in walls if w.is_solid])
        
        blocking_obstacle = None
        for obstacle in obstacles_to_check:
            if check_collision(player_rect, obstacle.get_rect()):
                blocking_obstacle = obstacle
                # Try moving only X or only Y
                test_x = (new_x + margin, old_y + margin, hitbox_size, hitbox_size)
                test_y = (old_x + margin, new_y + margin, hitbox_size, hitbox_size)
                
                if check_collision(test_x, obstacle.get_rect()):
                    can_move_x = False
                if check_collision(test_y, obstacle.get_rect()):
                    can_move_y = False
        
        # Corner sliding: if blocked in one direction, try to slide around corners
        if blocking_obstacle and (not can_move_x or not can_move_y):
            obs_rect = blocking_obstacle.get_rect()
            obs_x, obs_y, obs_w, obs_h = obs_rect
            player_center_x = old_x + self.size / 2
            player_center_y = old_y + self.size / 2
            obs_center_x = obs_x + obs_w / 2
            obs_center_y = obs_y + obs_h / 2
            
            # If moving horizontally and blocked, try to slide vertically
            if move_x != 0 and not can_move_x and can_move_y:
                # Check if we're close to the top or bottom edge
                top_dist = abs((player_center_y) - (obs_y + obs_h))
                bot_dist = abs((player_center_y) - obs_y)
                
                if top_dist < CORNER_SLIDE_THRESHOLD + hitbox_size / 2:
                    # Slide up
                    new_y += self.speed * dt * 0.5
                elif bot_dist < CORNER_SLIDE_THRESHOLD + hitbox_size / 2:
                    # Slide down
                    new_y -= self.speed * dt * 0.5
            
            # If moving vertically and blocked, try to slide horizontally
            if move_y != 0 and not can_move_y and can_move_x:
                # Check if we're close to the left or right edge
                right_dist = abs((player_center_x) - (obs_x + obs_w))
                left_dist = abs((player_center_x) - obs_x)
                
                if right_dist < CORNER_SLIDE_THRESHOLD + hitbox_size / 2:
                    # Slide right
                    new_x += self.speed * dt * 0.5
                elif left_dist < CORNER_SLIDE_THRESHOLD + hitbox_size / 2:
                    # Slide left
                    new_x -= self.speed * dt * 0.5
        
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
        
        # Create layered projectile with glow effect
        self.shapes = []
        
        # Outer glow
        glow_outer = shapes.Circle(0, 0, self.size, color=(255, 200, 50), batch=batch)
        glow_outer.opacity = 40
        self.shapes.append(glow_outer)
        
        glow_mid = shapes.Circle(0, 0, self.size * 0.75, color=(255, 220, 100), batch=batch)
        glow_mid.opacity = 80
        self.shapes.append(glow_mid)
        
        # Main projectile body
        main = shapes.Circle(0, 0, self.size // 2, color=YELLOW, batch=batch)
        self.shapes.append(main)
        
        # Bright core
        core = shapes.Circle(0, 0, self.size // 4, color=(255, 255, 200), batch=batch)
        self.shapes.append(core)
        
        # White hot center
        center = shapes.Circle(0, 0, self.size // 6, color=(255, 255, 255), batch=batch)
        self.shapes.append(center)
    
    def update(self):
        self.x += self.dx
        self.y += self.dy
        # Shape position will be updated by camera in game loop
    
    def update_shape_position(self, camera):
        """Update shape position based on camera"""
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        center_x = screen_x + self.size/2
        center_y = screen_y + self.size/2
        for shape in self.shapes:
            shape.x = center_x
            shape.y = center_y
    
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
        # Pathfinding state
        self.stuck_timer = 0.0
        self.last_position = (x, y)
    
    def find_path_around_obstacle(self, target_x, target_y, obstacles, dt):
        """Try to find a path around obstacles using steering behavior"""
        # Get direction to target
        dx = target_x - self.x
        dy = target_y - self.y
        distance = math.sqrt(dx**2 + dy**2)
        
        if distance == 0:
            return (0, 0)
        
        # Normalize direction
        dir_x = dx / distance
        dir_y = dy / distance
        
        # Check for obstacles in the path
        look_ahead = ENEMY_PATHFINDING_RANGE
        check_x = self.x + dir_x * look_ahead
        check_y = self.y + dir_y * look_ahead
        check_rect = (check_x - self.size/2, check_y - self.size/2, self.size, self.size)
        
        blocking_obstacle = None
        for obstacle in obstacles:
            if hasattr(obstacle, 'is_chopped') and obstacle.is_chopped:
                continue
            if check_collision(check_rect, obstacle.get_rect()):
                blocking_obstacle = obstacle
                break
        
        # If no obstacle, move directly
        if not blocking_obstacle:
            return (dir_x, dir_y)
        
        # Obstacle detected - try to steer around it
        # Get obstacle center
        obs_rect = blocking_obstacle.get_rect()
        obs_center_x = obs_rect[0] + obs_rect[2] / 2
        obs_center_y = obs_rect[1] + obs_rect[3] / 2
        
        # Calculate vector from obstacle to enemy
        avoid_dx = self.x - obs_center_x
        avoid_dy = self.y - obs_center_y
        avoid_dist = math.sqrt(avoid_dx**2 + avoid_dy**2)
        
        if avoid_dist > 0:
            # Normalize avoidance vector
            avoid_dx /= avoid_dist
            avoid_dy /= avoid_dist
            
            # Blend direct path with avoidance (weighted toward avoidance when close)
            obstacle_size = max(obs_rect[2], obs_rect[3])
            avoid_strength = max(0, 1.0 - (avoid_dist / (obstacle_size + self.size)))
            
            # Combine direction to target with avoidance
            steer_x = dir_x * (1.0 - avoid_strength) + avoid_dx * avoid_strength
            steer_y = dir_y * (1.0 - avoid_strength) + avoid_dy * avoid_strength
            
            # Normalize
            steer_len = math.sqrt(steer_x**2 + steer_y**2)
            if steer_len > 0:
                steer_x /= steer_len
                steer_y /= steer_len
            
            return (steer_x, steer_y)
        
        return (dir_x, dir_y)
    
    def update(self, player_x, player_y, dt, rocks=None, trees=None, walls=None):
        # Combine all obstacles
        all_obstacles = []
        if rocks:
            all_obstacles.extend(rocks)
        if trees:
            all_obstacles.extend([t for t in trees if not t.is_chopped])
        if walls:
            all_obstacles.extend([w for w in walls if w.is_solid])
        
        # Use pathfinding to get direction
        dir_x, dir_y = self.find_path_around_obstacle(player_x, player_y, all_obstacles, dt)
        
        # Calculate intended movement
        speed_per_frame = self.speed * dt * 60  # Convert to frame-based equivalent
        new_x = self.x + dir_x * speed_per_frame
        new_y = self.y + dir_y * speed_per_frame
        
        # Store old position
        old_x = self.x
        old_y = self.y
        
        # Check collision with obstacles before moving
        enemy_rect = (new_x, new_y, self.size, self.size)
        can_move_x = True
        can_move_y = True
        
        for obstacle in all_obstacles:
            if check_collision(enemy_rect, obstacle.get_rect()):
                # Try moving only X or only Y
                test_x = (new_x, old_y, self.size, self.size)
                test_y = (old_x, new_y, self.size, self.size)
                
                if check_collision(test_x, obstacle.get_rect()):
                    can_move_x = False
                if check_collision(test_y, obstacle.get_rect()):
                    can_move_y = False
        
        # Check if enemy is currently touching an obstacle
        current_rect = (self.x, self.y, self.size, self.size)
        touching_obstacle = None
        for obstacle in all_obstacles:
            if check_collision(current_rect, obstacle.get_rect()):
                touching_obstacle = obstacle
                break
        
        # If touching an obstacle, prioritize perpendicular movement to get around it
        if touching_obstacle:
            # Get obstacle center
            obs_rect = touching_obstacle.get_rect()
            obs_center_x = obs_rect[0] + obs_rect[2] / 2
            obs_center_y = obs_rect[1] + obs_rect[3] / 2
            
            # Calculate vector from obstacle to enemy
            avoid_dx = self.x - obs_center_x
            avoid_dy = self.y - obs_center_y
            avoid_dist = math.sqrt(avoid_dx**2 + avoid_dy**2)
            
            if avoid_dist > 0:
                # Normalize avoidance vector
                avoid_dx /= avoid_dist
                avoid_dy /= avoid_dist
                
                # Try perpendicular movement (rotate 90 degrees)
                # Try both perpendicular directions
                perp1_x = -avoid_dy
                perp1_y = avoid_dx
                perp2_x = avoid_dy
                perp2_y = -avoid_dx
                
                # Try first perpendicular direction
                test_new_x = self.x + perp1_x * speed_per_frame
                test_new_y = self.y + perp1_y * speed_per_frame
                test_rect = (test_new_x, test_new_y, self.size, self.size)
                can_move_perp1 = True
                for obstacle in all_obstacles:
                    if check_collision(test_rect, obstacle.get_rect()):
                        can_move_perp1 = False
                        break
                
                if can_move_perp1:
                    self.x = test_new_x
                    self.y = test_new_y
                else:
                    # Try second perpendicular direction
                    test_new_x = self.x + perp2_x * speed_per_frame
                    test_new_y = self.y + perp2_y * speed_per_frame
                    test_rect = (test_new_x, test_new_y, self.size, self.size)
                    can_move_perp2 = True
                    for obstacle in all_obstacles:
                        if check_collision(test_rect, obstacle.get_rect()):
                            can_move_perp2 = False
                            break
                    
                    if can_move_perp2:
                        self.x = test_new_x
                        self.y = test_new_y
                    # If both perpendicular directions blocked, try original movement
                    elif can_move_x or can_move_y:
                        if can_move_x:
                            self.x = new_x
                        if can_move_y:
                            self.y = new_y
            else:
                # If completely blocked, try perpendicular movement to original direction
                if not can_move_x and not can_move_y:
                    perp_x = -dir_y
                    perp_y = dir_x
                    test_new_x = self.x + perp_x * speed_per_frame
                    test_new_y = self.y + perp_y * speed_per_frame
                    test_rect = (test_new_x, test_new_y, self.size, self.size)
                    
                    can_move_perp = True
                    for obstacle in all_obstacles:
                        if check_collision(test_rect, obstacle.get_rect()):
                            can_move_perp = False
                            break
                    
                    if can_move_perp:
                        self.x = test_new_x
                        self.y = test_new_y
        else:
            # Not touching obstacle - apply normal movement
            if not can_move_x and not can_move_y:
                # Try moving perpendicular to find a way around
                perp_x = -dir_y
                perp_y = dir_x
                test_new_x = self.x + perp_x * speed_per_frame
                test_new_y = self.y + perp_y * speed_per_frame
                test_rect = (test_new_x, test_new_y, self.size, self.size)
                
                can_move_perp = True
                for obstacle in all_obstacles:
                    if check_collision(test_rect, obstacle.get_rect()):
                        can_move_perp = False
                        break
                
                if can_move_perp:
                    self.x = test_new_x
                    self.y = test_new_y
            else:
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

class Wall:
    """Player-built wooden wall"""
    def __init__(self, x, y, batch, owner=None):
        self.x = x  # World coordinates (center position)
        self.y = y
        self.size = WALL_SIZE
        self.batch = batch
        self.owner = owner  # Player who built the wall
        self.is_solid = False  # Becomes solid after owner leaves the hitbox
        
        # Wooden wall appearance - brown with wood grain effect
        self.shape = shapes.Rectangle(0, 0, self.size, self.size, color=(139, 90, 43), batch=batch)
        self.border = shapes.Rectangle(0, 0, self.size, self.size, color=(101, 67, 33), batch=batch)
        self.border.opacity = 200
        # Horizontal wood grain lines
        self.grain1 = shapes.Rectangle(0, 0, self.size - 4, 2, color=(120, 75, 35), batch=batch)
        self.grain2 = shapes.Rectangle(0, 0, self.size - 4, 2, color=(120, 75, 35), batch=batch)
        self.grain3 = shapes.Rectangle(0, 0, self.size - 4, 2, color=(120, 75, 35), batch=batch)
    
    def update_shape_position(self, camera):
        """Update shape position based on camera"""
        screen_x, screen_y = camera.world_to_screen(self.x - self.size // 2, self.y - self.size // 2)
        self.shape.x = screen_x
        self.shape.y = screen_y
        self.border.x = screen_x
        self.border.y = screen_y
        # Position grain lines
        self.grain1.x = screen_x + 2
        self.grain1.y = screen_y + self.size // 4
        self.grain2.x = screen_x + 2
        self.grain2.y = screen_y + self.size // 2
        self.grain3.x = screen_x + 2
        self.grain3.y = screen_y + 3 * self.size // 4
    
    def get_rect(self):
        """Return collision rectangle (centered on position)"""
        return (self.x - self.size // 2, self.y - self.size // 2, self.size, self.size)
    
    def check_owner_outside(self, player):
        """Check if the owner has moved outside the wall's hitbox"""
        if not self.is_solid and self.owner == player:
            player_rect = player.get_rect()
            wall_rect = self.get_rect()
            if not check_collision(player_rect, wall_rect):
                self.is_solid = True
                return True
        return False
    
    def delete(self):
        """Clean up shapes"""
        self.shape.delete()
        self.border.delete()
        self.grain1.delete()
        self.grain2.delete()
        self.grain3.delete()

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
        # Progress bar for harvesting
        self.progress_bar_bg = shapes.Rectangle(0, 0, self.size + 10, 4, color=(50, 50, 50), batch=batch)
        self.progress_bar_fg = shapes.Rectangle(0, 0, 0, 4, color=(0, 255, 0), batch=batch)
        self.progress_bar_bg.visible = False
        self.progress_bar_fg.visible = False
    
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
        
        # Update progress bar position (above the tree)
        bar_width = self.size + 10
        bar_height = 4
        self.progress_bar_bg.x = screen_x - bar_width // 2
        self.progress_bar_bg.y = screen_y + self.size // 2 + 10
        self.progress_bar_fg.x = screen_x - bar_width // 2
        self.progress_bar_fg.y = screen_y + self.size // 2 + 10
        
        # Update progress bar visibility and width
        if self.current_chop_target and self.chop_progress > 0:
            self.progress_bar_bg.visible = True
            self.progress_bar_fg.visible = True
            self.progress_bar_fg.width = bar_width * self.chop_progress
        else:
            self.progress_bar_bg.visible = False
            self.progress_bar_fg.visible = False
    
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
                self.progress_bar_bg.delete()
                self.progress_bar_fg.delete()
                return True  # Tree chopped down
        return False

def spawn_enemy(batch, player_x=None, player_y=None, obstacles=None):
    """Spawn an enemy at a valid location (not inside obstacles)"""
    obstacles = obstacles or []
    max_attempts = 50  # Try up to 50 times to find a valid spawn location
    
    for attempt in range(max_attempts):
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
        else:
            # Fallback: spawn at world edges
            side = random.randint(0, 3)
            if side == 0:  # Top
                spawn_x = random.randint(0, WORLD_WIDTH)
                spawn_y = WORLD_HEIGHT
            elif side == 1:  # Right
                spawn_x = WORLD_WIDTH
                spawn_y = random.randint(0, WORLD_HEIGHT)
            elif side == 2:  # Bottom
                spawn_x = random.randint(0, WORLD_WIDTH)
                spawn_y = -ENEMY_SIZE
            else:  # Left
                spawn_x = -ENEMY_SIZE
                spawn_y = random.randint(0, WORLD_HEIGHT)
        
        # Check if spawn location is valid (not inside obstacles)
        spawn_rect = (spawn_x, spawn_y, ENEMY_SIZE, ENEMY_SIZE)
        valid_spawn = True
        
        for obstacle in obstacles:
            # Skip chopped trees
            if hasattr(obstacle, 'is_chopped') and obstacle.is_chopped:
                continue
            if check_collision(spawn_rect, obstacle.get_rect()):
                valid_spawn = False
                break
        
        if valid_spawn:
            return Enemy(spawn_x, spawn_y, batch)
    
    # If we couldn't find a valid spawn after max attempts, spawn at edge anyway
    # (better than not spawning at all)
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
    """Generate rocks randomly across the world, snapped to grid and clustered"""
    rocks = []
    attempts = 0
    max_attempts = num_rocks * 30
    
    # Create cluster centers (fewer clusters than rocks)
    num_clusters = max(3, num_rocks // 8)  # About 8 rocks per cluster
    cluster_centers = []
    
    for _ in range(num_clusters):
        cluster_x = random.randint(GRID_SIZE * 5, WORLD_WIDTH - GRID_SIZE * 5)
        cluster_y = random.randint(GRID_SIZE * 5, WORLD_HEIGHT - GRID_SIZE * 5)
        # Snap cluster center to grid
        cluster_x, cluster_y = snap_to_grid(cluster_x, cluster_y)
        cluster_centers.append((cluster_x, cluster_y))
    
    # Generate rocks in clusters
    rocks_per_cluster = num_rocks // num_clusters
    remaining_rocks = num_rocks
    
    for cluster_x, cluster_y in cluster_centers:
        cluster_rocks = 0
        cluster_max = rocks_per_cluster if remaining_rocks > rocks_per_cluster else remaining_rocks
        
        # Try to place rocks near this cluster center
        cluster_radius = GRID_SIZE * 8  # Cluster radius in pixels
        
        while cluster_rocks < cluster_max and attempts < max_attempts:
            attempts += 1
            
            # Random position within cluster radius
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(0, cluster_radius)
            x = cluster_x + math.cos(angle) * distance
            y = cluster_y + math.sin(angle) * distance
            
            # Snap to grid
            x, y = snap_to_grid(x, y)
            
            # Use uniform size (grid-aligned)
            size = GRID_SIZE
            
            # Keep within world bounds
            if x < size or x > WORLD_WIDTH - size or y < size or y > WORLD_HEIGHT - size:
                continue
            
            # Skip if too close to starting position
            if exclude_x and exclude_y:
                dist = math.sqrt((x - exclude_x)**2 + (y - exclude_y)**2)
                if dist < exclude_radius:
                    continue
            
            # Check if this position overlaps with existing rocks
            new_rect = (x - size // 2, y - size // 2, size, size)
            overlap = False
            for existing in rocks:
                if check_collision(new_rect, existing.get_rect()):
                    overlap = True
                    break
            
            if not overlap:
                rocks.append(Rock(x - size // 2, y - size // 2, size, batch))
                cluster_rocks += 1
                remaining_rocks -= 1
        
        if remaining_rocks <= 0:
            break
    
    # Fill remaining rocks randomly if we didn't place enough
    while len(rocks) < num_rocks and attempts < max_attempts:
        attempts += 1
        x = random.randint(GRID_SIZE * 2, WORLD_WIDTH - GRID_SIZE * 2)
        y = random.randint(GRID_SIZE * 2, WORLD_HEIGHT - GRID_SIZE * 2)
        x, y = snap_to_grid(x, y)
        size = GRID_SIZE
        
        # Skip if too close to starting position
        if exclude_x and exclude_y:
            dist = math.sqrt((x - exclude_x)**2 + (y - exclude_y)**2)
            if dist < exclude_radius:
                continue
        
        new_rect = (x - size // 2, y - size // 2, size, size)
        overlap = False
        for existing in rocks:
            if check_collision(new_rect, existing.get_rect()):
                overlap = True
                break
        
        if not overlap:
            rocks.append(Rock(x - size // 2, y - size // 2, size, batch))
    
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

def snap_to_grid(x, y):
    """Snap coordinates to the grid"""
    grid_x = (x // GRID_SIZE) * GRID_SIZE + GRID_SIZE // 2
    grid_y = (y // GRID_SIZE) * GRID_SIZE + GRID_SIZE // 2
    return grid_x, grid_y

class GameOverWindow(pyglet.window.Window):
    """Game over screen with options to retry or return to menu"""
    def __init__(self, day_count, is_multiplayer=False, is_host=False, host_ip='127.0.0.1'):
        super().__init__(width=SCREEN_WIDTH, height=SCREEN_HEIGHT, caption="Game Over")
        self.batch = pyglet.graphics.Batch()
        self.is_multiplayer = is_multiplayer
        self.is_host = is_host
        self.host_ip = host_ip
        
        # Game over title - use BASE dimensions for positioning
        self.title_label = pyglet.text.Label(
            'GAME OVER',
            font_name='Arial',
            font_size=48,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 150,
            anchor_x='center', anchor_y='center',
            color=(255, 50, 50, 255),
            batch=self.batch
        )
        
        # Day count
        self.day_label = pyglet.text.Label(
            f'You survived {day_count} day{"s" if day_count != 1 else ""}',
            font_name='Arial',
            font_size=24,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 + 50,
            anchor_x='center', anchor_y='center',
            color=WHITE,
            batch=self.batch
        )
        
        # Options
        self.retry_label = pyglet.text.Label(
            '1. Try Again',
            font_name='Arial',
            font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 - 30,
            anchor_x='center', anchor_y='center',
            color=GREEN,
            batch=self.batch
        )
        
        self.menu_label = pyglet.text.Label(
            '2. Return to Main Menu',
            font_name='Arial',
            font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 - 80,
            anchor_x='center', anchor_y='center',
            color=CYAN,
            batch=self.batch
        )
        
        self.instructions_label = pyglet.text.Label(
            'Press 1 or 2 to select',
            font_name='Arial',
            font_size=16,
            x=SCREEN_WIDTH // 2, y=100,
            anchor_x='center', anchor_y='center',
            color=WHITE,
            batch=self.batch
        )
    
    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.NUM_1 or symbol == pyglet.window.key._1:
            self.retry_game()
        elif symbol == pyglet.window.key.NUM_2 or symbol == pyglet.window.key._2:
            self.return_to_menu()
    
    def retry_game(self):
        """Restart the game with same settings"""
        window = GameWindow(is_multiplayer=self.is_multiplayer, is_host=self.is_host, host_ip=self.host_ip)
        ScreenManager.set_window(window)
    
    def return_to_menu(self):
        """Go back to main menu"""
        menu = MenuWindow()
        ScreenManager.set_window(menu)
    
    def on_draw(self):
        gl.glClearColor(0, 0, 0, 1)
        self.clear()
        self.batch.draw()

class MenuWindow(pyglet.window.Window):
    def __init__(self):
        super().__init__(width=SCREEN_WIDTH, height=SCREEN_HEIGHT, caption="Cube Shooter Game - Menu")
        self.batch = pyglet.graphics.Batch()
        
        # Menu items - use BASE dimensions for positioning
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
        window = GameWindow(is_multiplayer=False)
        ScreenManager.set_window(window)
    
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
        
        window = GameWindow(is_multiplayer=True, is_host=True)
        ScreenManager.set_window(window)
    
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
        
        window = GameWindow(is_multiplayer=True, is_host=False, host_ip=host_ip)
        ScreenManager.set_window(window)
    
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
        self.game_active = True  # Track if game is still running
        self.host_ip = host_ip  # Store for game over screen
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
        
        # Player-built structures
        self.walls = []
        
        # Build mode state
        self.build_menu_open = False
        self.selected_building = 1  # Default to first building (wooden wall)
        self.building_types = {
            1: {'name': 'Wooden Wall', 'cost': WALL_WOOD_COST, 'resource': 'wood'}
        }
        
        # Build menu UI (created but hidden initially) - use BASE dimensions
        self.build_menu_bg = shapes.Rectangle(
            SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT - 60,
            300, 50,
            color=(30, 30, 30),
            batch=self.batch
        )
        self.build_menu_bg.opacity = 180
        self.build_menu_bg.visible = False
        
        self.build_menu_title = pyglet.text.Label(
            'BUILD MENU (1-9 to select, F to build)',
            font_name='Arial',
            font_size=10,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 18,
            anchor_x='center', anchor_y='center',
            color=(255, 255, 255, 255),
            batch=self.batch
        )
        self.build_menu_title.visible = False
        
        self.build_menu_item1 = pyglet.text.Label(
            f'[1] Wooden Wall ({WALL_WOOD_COST} wood)',
            font_name='Arial',
            font_size=12,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 42,
            anchor_x='center', anchor_y='center',
            color=(255, 255, 0, 255),  # Yellow for selected
            batch=self.batch
        )
        self.build_menu_item1.visible = False
        
        # Enemy spawning (only host spawns enemies in multiplayer)
        self.enemy_spawn_rate = INITIAL_ENEMY_SPAWN_RATE
        self.enemy_spawn_counter = 0
        self.enemy_spawn_timer = 0.0  # Initialize timer
        self.game_time = 0.0
        
        # Day/Night cycle state
        self.day_count = 1  # Start on day 1
        self.is_night = False
        self.cycle_time = 0.0  # Time within current day or night
        self.night_enemies_spawned = 0  # Track enemies spawned this night
        
        # Track mouse position (in BASE coordinates)
        self.mouse_x = SCREEN_WIDTH // 2
        self.mouse_y = SCREEN_HEIGHT // 2
        
        # Track pressed keys
        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)
        
        # Fire rate tracking
        self.last_fire_time = 0.0
        self.arrow_keys_pressed = {
            pyglet.window.key.UP: False,
            pyglet.window.key.DOWN: False,
            pyglet.window.key.LEFT: False,
            pyglet.window.key.RIGHT: False
        }
        
        # Reload progress indicator (small circle next to player)
        self.reload_circle_radius = 5  # Very small circle
        self.reload_circle_bg = shapes.Circle(
            0, 0, 
            self.reload_circle_radius, 
            color=(50, 50, 50), 
            batch=self.batch
        )
        self.reload_circle_bg.opacity = 150  # Translucent
        
        # Arc segments for progress (using multiple small arcs)
        self.reload_arc_segments = []  # List of arc segment shapes
        self.reload_arc_x = 0
        self.reload_arc_y = 0
        self.reload_arc_progress = 0.0
        
        # Enemy counter (top right, smaller)
        self.score_label = pyglet.text.Label(
            '0',
            font_name='Arial',
            font_size=14,
            x=SCREEN_WIDTH - 10, y=SCREEN_HEIGHT - 18,
            anchor_x='right', anchor_y='center',
            color=WHITE,
            batch=self.batch
        )
        
        # Wood icon and counter (top left) - log shape
        # Log base (rounded rectangle effect using multiple shapes)
        log_y = SCREEN_HEIGHT - 20
        log_x = 10
        # Main log body
        self.wood_icon = shapes.Rectangle(
            log_x, log_y - 12,
            14, 12,
            color=(139, 90, 43),  # Brown wood color
            batch=self.batch
        )
        # Log top (rounded effect)
        self.wood_top = shapes.Circle(
            log_x + 7, log_y - 1,
            7,
            color=(139, 90, 43),
            batch=self.batch
        )
        # Log bottom (rounded effect)
        self.wood_bottom = shapes.Circle(
            log_x + 7, log_y - 12,
            7,
            color=(139, 90, 43),
            batch=self.batch
        )
        # Wood grain rings (concentric circles on the end)
        self.wood_ring1 = shapes.Circle(
            log_x + 7, log_y - 1,
            4,
            color=(120, 75, 35),  # Darker brown for grain
            batch=self.batch
        )
        self.wood_ring2 = shapes.Circle(
            log_x + 7, log_y - 1,
            2,
            color=(101, 67, 33),  # Even darker for inner ring
            batch=self.batch
        )
        self.wood_label = pyglet.text.Label(
            '0',
            font_name='Arial',
            font_size=16,
            x=30, y=log_y - 6,
            anchor_y='center',
            color=WHITE,
            batch=self.batch
        )
        
        # Coin icon and counter (top left, below wood)
        coin_y = SCREEN_HEIGHT - 40
        # Coin outer circle (gold)
        self.coin_icon = shapes.Circle(
            16, coin_y,
            8,
            color=(255, 215, 0),  # Gold color
            batch=self.batch
        )
        # Coin inner highlight
        self.coin_highlight = shapes.Circle(
            16, coin_y,
            5,
            color=(255, 235, 100),  # Lighter gold for highlight
            batch=self.batch
        )
        self.coin_label = pyglet.text.Label(
            '0',
            font_name='Arial',
            font_size=16,
            x=30, y=coin_y,
            anchor_y='center',
            color=WHITE,
            batch=self.batch
        )
        
        # Day/Night cycle labels (bottom left)
        self.day_label = pyglet.text.Label(
            'Day 1',
            font_name='Arial',
            font_size=18,
            x=10, y=30,
            color=(255, 200, 50, 255),  # Golden yellow
            batch=self.batch
        )
        
        self.time_label = pyglet.text.Label(
            'Daytime - Gather resources!',
            font_name='Arial',
            font_size=14,
            x=10, y=10,
            color=(255, 255, 150, 255),  # Light yellow
            batch=self.batch
        )
        
        # Night warning overlay (hidden by default)
        self.night_warning = pyglet.text.Label(
            'NIGHT APPROACHES!',
            font_name='Arial',
            font_size=24,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 + 50,
            anchor_x='center', anchor_y='center',
            color=(255, 50, 50, 255),
            batch=self.batch
        )
        self.night_warning.visible = False
        self.night_warning_timer = 0.0
        
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
        # Track arrow key presses for continuous shooting
        if symbol == pyglet.window.key.UP:
            self.arrow_keys_pressed[pyglet.window.key.UP] = True
        elif symbol == pyglet.window.key.DOWN:
            self.arrow_keys_pressed[pyglet.window.key.DOWN] = True
        elif symbol == pyglet.window.key.LEFT:
            self.arrow_keys_pressed[pyglet.window.key.LEFT] = True
        elif symbol == pyglet.window.key.RIGHT:
            self.arrow_keys_pressed[pyglet.window.key.RIGHT] = True
        
        # Build mode - F key toggles menu, also builds when menu is open
        elif symbol == pyglet.window.key.F:
            if self.build_menu_open:
                # Try to build the selected structure
                self.try_build()
            else:
                # Open build menu
                self.toggle_build_menu(True)
        
        # Number keys select building type (when menu is open)
        elif self.build_menu_open:
            if symbol == pyglet.window.key._1 or symbol == pyglet.window.key.NUM_1:
                self.select_building(1)
            # Add more building selections here as needed
        
        # Escape closes build menu
        if symbol == pyglet.window.key.ESCAPE:
            if self.build_menu_open:
                self.toggle_build_menu(False)
    
    def on_key_release(self, symbol, modifiers):
        # Track arrow key releases
        if symbol == pyglet.window.key.UP:
            self.arrow_keys_pressed[pyglet.window.key.UP] = False
        elif symbol == pyglet.window.key.DOWN:
            self.arrow_keys_pressed[pyglet.window.key.DOWN] = False
        elif symbol == pyglet.window.key.LEFT:
            self.arrow_keys_pressed[pyglet.window.key.LEFT] = False
        elif symbol == pyglet.window.key.RIGHT:
            self.arrow_keys_pressed[pyglet.window.key.RIGHT] = False
    
    def toggle_build_menu(self, show):
        """Toggle the build menu visibility"""
        self.build_menu_open = show
        self.build_menu_bg.visible = show
        self.build_menu_title.visible = show
        self.build_menu_item1.visible = show
        self.update_build_menu_selection()
    
    def select_building(self, building_id):
        """Select a building type"""
        if building_id in self.building_types:
            self.selected_building = building_id
            self.update_build_menu_selection()
    
    def update_build_menu_selection(self):
        """Update the build menu to show which item is selected"""
        # Update item 1 color based on selection
        if self.selected_building == 1:
            self.build_menu_item1.color = (255, 255, 0, 255)  # Yellow for selected
        else:
            self.build_menu_item1.color = (200, 200, 200, 255)  # Gray for unselected
    
    def try_build(self):
        """Try to build the selected structure"""
        if self.selected_building not in self.building_types:
            return
        
        building = self.building_types[self.selected_building]
        cost = building['cost']
        resource = building['resource']
        
        # Check if player has enough resources
        if resource == 'wood' and self.player.wood >= cost:
            # Build wooden wall at player's position, snapped to grid
            player_center_x, player_center_y = self.player.get_center()
            grid_x, grid_y = snap_to_grid(player_center_x, player_center_y)
            
            # Check if there's already a wall at this grid position
            wall_rect = (grid_x - WALL_SIZE // 2, grid_y - WALL_SIZE // 2, WALL_SIZE, WALL_SIZE)
            can_build = True
            for existing_wall in self.walls:
                if check_collision(wall_rect, existing_wall.get_rect()):
                    can_build = False
                    break
            
            # Also check for rocks at this position
            if can_build:
                for rock in self.rocks:
                    if check_collision(wall_rect, rock.get_rect()):
                        can_build = False
                        break
            
            if can_build:
                # Create the wall centered on the grid position
                wall = Wall(grid_x, grid_y, self.batch, owner=self.player)
                self.walls.append(wall)
                
                # Deduct resources
                self.player.wood -= cost
                
                # Wall will become solid once player moves outside it
    
    def update_day_night_cycle(self):
        """Update the day/night cycle and related UI"""
        if not self.is_night:
            # Currently daytime
            time_remaining = DAY_LENGTH - self.cycle_time
            
            # Show warning when night is approaching (last 5 seconds of day)
            if time_remaining <= 5.0 and time_remaining > 0:
                self.night_warning.visible = True
                self.night_warning.text = f'NIGHT APPROACHES IN {int(time_remaining) + 1}...'
            else:
                self.night_warning.visible = False
            
            # Transition to night
            if self.cycle_time >= DAY_LENGTH:
                self.is_night = True
                self.cycle_time = 0.0
                self.night_enemies_spawned = 0
                self.night_warning.visible = False
                # Flash warning at start of night
                self.night_warning.text = 'NIGHT HAS FALLEN!'
                self.night_warning.visible = True
                self.night_warning_timer = 2.0  # Show for 2 seconds
            
            # Update time label
            mins = int(time_remaining // 60)
            secs = int(time_remaining % 60)
            self.time_label.text = f'Day - {mins}:{secs:02d} until night'
            self.time_label.color = (255, 255, 150, 255)  # Light yellow
            self.day_label.color = (255, 200, 50, 255)  # Golden yellow
        else:
            # Currently nighttime
            time_remaining = NIGHT_LENGTH - self.cycle_time
            
            # Transition to day
            if self.cycle_time >= NIGHT_LENGTH:
                self.is_night = False
                self.cycle_time = 0.0
                self.day_count += 1
                self.night_warning.text = 'DAWN BREAKS!'
                self.night_warning.visible = True
                self.night_warning_timer = 2.0  # Show for 2 seconds
            
            # Update time label
            mins = int(time_remaining // 60)
            secs = int(time_remaining % 60)
            self.time_label.text = f'Night - {mins}:{secs:02d} until dawn'
            self.time_label.color = (200, 100, 100, 255)  # Reddish
            self.day_label.color = (150, 150, 200, 255)  # Pale blue
        
        # Update day counter
        self.day_label.text = f'Day {self.day_count}'
        
        # Handle night warning timer
        if self.night_warning_timer > 0:
            self.night_warning_timer -= 1.0 / FPS
            if self.night_warning_timer <= 0:
                self.night_warning.visible = False
    
    def try_shoot(self, dt):
        """Try to shoot a projectile if fire rate allows and arrow keys are pressed"""
        current_time = self.game_time
        
        # Check if enough time has passed since last shot
        if current_time - self.last_fire_time < PROJECTILE_FIRE_RATE:
            return
        
        # Determine shooting direction from pressed arrow keys
        direction_x = 0
        direction_y = 0
        
        if self.arrow_keys_pressed[pyglet.window.key.UP]:
            direction_y = 1
        elif self.arrow_keys_pressed[pyglet.window.key.DOWN]:
            direction_y = -1
        
        if self.arrow_keys_pressed[pyglet.window.key.LEFT]:
            direction_x = -1
        elif self.arrow_keys_pressed[pyglet.window.key.RIGHT]:
            direction_x = 1
        
        # If an arrow key is pressed, shoot a projectile
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
            self.last_fire_time = current_time
    
    def update(self, dt):
        # Skip update if game is no longer active
        if not self.game_active:
            return
        
        self.frame_count += 1
        self.game_time += dt
        
        # Update day/night cycle
        self.cycle_time += dt
        self.update_day_night_cycle()
        
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
        self.player.update(self.keys, dt, rocks=self.rocks, trees=self.trees, walls=self.walls)
        
        # Check if player has left any newly placed walls (make them solid)
        for wall in self.walls:
            wall.check_owner_outside(self.player)
        
        # Try to shoot (handles fire rate and held keys)
        self.try_shoot(dt)
        
        # Update reload progress indicator
        current_time = self.game_time
        time_since_last_shot = current_time - self.last_fire_time
        reload_progress = min(1.0, time_since_last_shot / PROJECTILE_FIRE_RATE)
        
        # Position reload circle at top right of player
        player_center_x, player_center_y = self.player.get_center()
        screen_x, screen_y = self.camera.world_to_screen(player_center_x, player_center_y)
        # Position at top right of player cube (offset by player size/2 + small gap)
        reload_x = screen_x + self.player.size // 2 + self.reload_circle_radius + 2
        reload_y = screen_y + self.player.size // 2 + self.reload_circle_radius + 2
        
        self.reload_circle_bg.x = reload_x
        self.reload_circle_bg.y = reload_y
        self.reload_arc_x = reload_x
        self.reload_arc_y = reload_y
        self.reload_arc_progress = reload_progress
        
        # Update visibility
        if reload_progress >= 1.0:
            # Hide when fully reloaded
            self.reload_circle_bg.visible = False
            self._clear_reload_arc()
        else:
            # Show and update arc
            self.reload_circle_bg.visible = True
            self._update_reload_arc()
        
        # Update player sprite position (camera-based)
        self.player.update_sprite_position(self.camera)
        
        # Update other player sprite if multiplayer
        if self.other_player:
            self.other_player.update_sprite_position(self.camera)
        
        # Handle harvesting (spacebar) - dedicated harvesting key
        harvest_key_pressed = self.keys[pyglet.window.key.SPACE]
        nearby_tree = None
        
        if harvest_key_pressed and self.player:
            # Get player center position
            player_center_x, player_center_y = self.player.get_center()
            
            # Check if player is within harvest range of any tree (distance-based, not collision)
            for tree in self.trees:
                if tree.is_chopped:
                    continue
                
                # Get tree center position
                tree_rect = tree.get_rect()
                tree_center_x = tree_rect[0] + tree_rect[2] / 2
                tree_center_y = tree_rect[1] + tree_rect[3] / 2
                
                # Calculate distance from player center to tree center
                dx = player_center_x - tree_center_x
                dy = player_center_y - tree_center_y
                distance = math.sqrt(dx**2 + dy**2)
                
                # Check if within harvest range
                if distance <= HARVEST_RANGE:
                    # If multiple trees in range, pick the closest one
                    if nearby_tree is None:
                        nearby_tree = tree
                    else:
                        # Check if this tree is closer
                        old_tree_rect = nearby_tree.get_rect()
                        old_tree_center_x = old_tree_rect[0] + old_tree_rect[2] / 2
                        old_tree_center_y = old_tree_rect[1] + old_tree_rect[3] / 2
                        old_dx = player_center_x - old_tree_center_x
                        old_dy = player_center_y - old_tree_center_y
                        old_distance = math.sqrt(old_dx**2 + old_dy**2)
                        
                        if distance < old_distance:
                            nearby_tree = tree
                    break  # Found a tree, can harvest it
        
        # Update tree chopping (harvesting)
        for tree in self.trees:
            if tree == nearby_tree and harvest_key_pressed:
                tree.current_chop_target = self.player
                if tree.update_chop(dt):
                    # Tree chopped down - player gets wood
                    self.player.wood += 1
                    self.trees.remove(tree)
            else:
                tree.current_chop_target = None
                tree.chop_progress = 0.0
        
        # Update projectiles
        # Clean up projectiles that go off-world
        for projectile in self.projectiles[:]:  # Iterate copy
            if projectile.is_off_world():
                for shape in projectile.shapes:
                    shape.delete()
                self.projectiles.remove(projectile)
        
        for projectile in self.projectiles:
            projectile.update()
            projectile.update_shape_position(self.camera)
        
        # Enemy spawning (only at night, only host in multiplayer)
        if self.is_night and (not self.is_multiplayer or (self.is_host and self.network and self.network.connected)):
            # Calculate night difficulty based on day count
            night_spawn_multiplier = NIGHT_SPAWN_MULTIPLIER_BASE + (self.day_count - 1) * NIGHT_SPAWN_MULTIPLIER_PER_DAY
            night_max_enemies = NIGHT_MAX_ENEMIES_BASE + (self.day_count - 1) * NIGHT_MAX_ENEMIES_PER_DAY
            night_max_enemies = min(night_max_enemies, MAX_ENEMIES)  # Cap at absolute max
            
            # Calculate target spawn interval in seconds (faster at night, gets faster each day)
            base_frames_per_spawn = INITIAL_ENEMY_SPAWN_RATE - (self.cycle_time * ENEMY_SPAWN_ACCELERATION * night_spawn_multiplier)
            frames_per_spawn = max(MIN_ENEMY_SPAWN_RATE, base_frames_per_spawn)
            spawn_interval = frames_per_spawn / FPS / night_spawn_multiplier  # Faster spawns at night
            
            self.enemy_spawn_timer += dt
            if len(self.enemies) < night_max_enemies and self.enemy_spawn_timer >= spawn_interval:
                # Get all obstacles for spawn validation (including solid walls)
                all_obstacles = list(self.rocks) + [t for t in self.trees if not t.is_chopped] + [w for w in self.walls if w.is_solid]
                enemy = spawn_enemy(self.batch, player_center_x, player_center_y, obstacles=all_obstacles)
                self.enemies.append(enemy)
                self.night_enemies_spawned += 1
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
        # Pass all obstacles (rocks and non-chopped trees) for collision and pathfinding
        all_obstacles = list(self.rocks) + [t for t in self.trees if not t.is_chopped]
        for enemy in self.enemies:
            enemy.update(player_center_x, player_center_y, dt, rocks=self.rocks, trees=self.trees, walls=self.walls)
            enemy.update_shape_position(self.camera)
        
        # Update rock positions
        for rock in self.rocks:
            rock.update_shape_position(self.camera)
        
        # Update tree positions
        for tree in self.trees:
            tree.update_shape_position(self.camera)
        
        # Update wall positions
        for wall in self.walls:
            wall.update_shape_position(self.camera)
        
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
        
        # Projectiles vs walls
        for wall in self.walls:
            if wall.is_solid:  # Only solid walls block projectiles
                for projectile in self.projectiles:
                    if check_collision(wall.get_rect(), projectile.get_rect()):
                        if projectile not in projectiles_to_remove:
                            projectiles_to_remove.append(projectile)
        
        # Player vs rocks collision is now handled in player.update() method
        
        # Remove collided objects
        for enemy in enemies_to_remove:
            # Give player coins for defeating enemy
            if self.player:
                self.player.coins += 1
            enemy.shape.delete()
            enemy.border.delete()
            self.enemies.remove(enemy)
        for projectile in projectiles_to_remove:
            for shape in projectile.shapes:
                shape.delete()
            self.projectiles.remove(projectile)
        
        # Check if player is hit by enemy
        if self.player:
            player_rect = self.player.get_hitbox()  # Use smaller hitbox for fairer collision
            for enemy in self.enemies:
                if check_collision(player_rect, enemy.get_rect()):
                    # Show game over screen instead of closing
                    self.show_game_over()
                    return
        
        # Update enemy counter (top right)
        self.score_label.text = str(len(self.enemies))
        
        # Update wood counter (top left)
        self.wood_label.text = str(self.player.wood)
        
        # Update coin counter (top left, below wood)
        self.coin_label.text = str(self.player.coins)
    
    def _clear_reload_arc(self):
        """Clear all arc segments"""
        for segment in self.reload_arc_segments:
            segment.delete()
        self.reload_arc_segments.clear()
    
    def _update_reload_arc(self):
        """Update the reload arc using filled segments"""
        # Clear old segments
        self._clear_reload_arc()
        
        if self.reload_arc_progress <= 0:
            return
        
        # Create filled arc using small filled rectangles positioned along the circle
        # Start from top (-90 degrees) and fill clockwise
        num_segments = max(24, int(48 * self.reload_arc_progress))  # More segments for smoother arc
        angle_range = 2 * math.pi * self.reload_arc_progress  # Total angle to fill
        start_angle = -math.pi / 2  # Start at top (-90 degrees)
        
        center_x = self.reload_arc_x
        center_y = self.reload_arc_y
        radius = self.reload_circle_radius
        
        # Create small filled rectangles along the arc path
        for i in range(num_segments):
            angle = start_angle + (angle_range * i / num_segments)
            
            # Position along the circle
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            
            # Create a small filled rectangle (rotated to follow the arc)
            # Use a small square that's slightly rotated
            segment = shapes.Rectangle(
                x - 1, y - 1,  # Small offset to center
                2, 2,  # Small size
                color=(255, 255, 0),
                batch=self.batch
            )
            segment.opacity = 150  # Translucent
            self.reload_arc_segments.append(segment)
    
    def on_draw(self):
        # Change background color based on day/night
        if self.is_night:
            # Night - dark blue/black
            night_progress = self.cycle_time / NIGHT_LENGTH
            # Darken progressively, then lighten near dawn
            if night_progress < 0.5:
                intensity = 0.05 - (night_progress * 0.05)  # Get darker
            else:
                intensity = (night_progress - 0.5) * 0.1  # Get lighter near dawn
            gl.glClearColor(intensity * 0.3, intensity * 0.3, intensity * 0.8, 1)
        else:
            # Day - transitions from dark to light and back
            day_progress = self.cycle_time / DAY_LENGTH
            if day_progress < 0.15:
                # Dawn - orange/yellow tint
                intensity = 0.1 + (day_progress / 0.15) * 0.15
                gl.glClearColor(intensity * 0.8, intensity * 0.5, intensity * 0.2, 1)
            elif day_progress > 0.85:
                # Dusk - orange/red tint
                dusk_progress = (day_progress - 0.85) / 0.15
                intensity = 0.25 - (dusk_progress * 0.15)
                gl.glClearColor(intensity * 0.8, intensity * 0.4, intensity * 0.2, 1)
            else:
                # Midday - darker background (still playable)
                gl.glClearColor(0.08, 0.08, 0.12, 1)
        
        self.clear()
        self.batch.draw()
    
    def show_game_over(self):
        """Show game over screen"""
        self.game_active = False
        game_over = GameOverWindow(
            day_count=self.day_count,
            is_multiplayer=self.is_multiplayer,
            is_host=self.is_host,
            host_ip=self.host_ip
        )
        ScreenManager.set_window(game_over)
    
    def on_close(self):
        """Clean up when window closes"""
        self.game_active = False
        # Unschedule the update function to prevent it from running after close
        pyglet.clock.unschedule(self.update)
        # Clean up reload arc segments
        self._clear_reload_arc()
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
    ScreenManager.set_window(menu)
    pyglet.app.run()

if __name__ == "__main__":
    main()
