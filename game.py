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
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any, Type

# ============================================================================
# ECS CORE INFRASTRUCTURE
# ============================================================================

class Entity:
    """An entity is just a unique ID with a set of components."""
    _next_id = 0
    
    def __init__(self, world: 'World' = None):
        self.id = Entity._next_id
        Entity._next_id += 1
        self.components: Dict[Type, Any] = {}
        self.active = True
        self.world = world
    
    def add_component(self, component) -> 'Entity':
        comp_type = type(component)
        self.components[comp_type] = component
        if self.world:
            self.world._register_component(comp_type, self)
        return self
    
    def get_component(self, component_type: Type):
        return self.components.get(component_type)
    
    def has_component(self, component_type: Type) -> bool:
        return component_type in self.components
    
    def has_components(self, *component_types) -> bool:
        return all(ct in self.components for ct in component_types)
    
    def remove_component(self, component_type: Type):
        if component_type in self.components:
            if self.world:
                self.world._unregister_component(component_type, self.id)
            del self.components[component_type]

class World:
    """The ECS World manages all entities and systems."""
    def __init__(self):
        self.entities: Dict[int, Entity] = {}
        self.systems: List['System'] = []
        self.entities_to_remove: Set[int] = set()
        self.batch = None
        self.camera = None
        self.component_index: Dict[Type, Set[int]] = {}
        self.spatial = None
        self.render_resources = None
    
    def create_entity(self) -> Entity:
        entity = Entity(self)
        self.entities[entity.id] = entity
        return entity
    
    def remove_entity(self, entity_id: int):
        self.entities_to_remove.add(entity_id)
    
    def get_entity(self, entity_id: int) -> Optional[Entity]:
        return self.entities.get(entity_id)
    
    def get_entities_with(self, *component_types) -> List[Entity]:
        if not component_types:
            return [e for e in self.entities.values() if e.active]
        
        index_sets = []
        for comp_type in component_types:
            entity_ids = self.component_index.get(comp_type)
            if not entity_ids:
                return []
            index_sets.append(entity_ids)
        
        index_sets.sort(key=len)
        common_ids = set(index_sets[0])
        for ids in index_sets[1:]:
            common_ids &= ids
            if not common_ids:
                return []
        
        return [self.entities[e_id] for e_id in common_ids if self.entities[e_id].active]
    
    def add_system(self, system: 'System'):
        system.world = self
        self.systems.append(system)
        self.systems.sort(key=lambda s: s.priority)
    
    def update(self, dt: float):
        # Run all systems
        for system in self.systems:
            if system.active:
                system.update(dt)
        
        # Clean up removed entities
        for entity_id in self.entities_to_remove:
            if entity_id in self.entities:
                entity = self.entities[entity_id]
                # Clean up sprite components
                sprite_comp = entity.get_component(SpriteComponent)
                if sprite_comp:
                    sprite_comp.cleanup()
                self._unregister_entity_components(entity)
                del self.entities[entity_id]
        self.entities_to_remove.clear()
    
    def clear(self):
        for entity in list(self.entities.values()):
            sprite_comp = entity.get_component(SpriteComponent)
            if sprite_comp:
                sprite_comp.cleanup()
            self._unregister_entity_components(entity)
        self.entities.clear()
        self.component_index.clear()
        Entity._next_id = 0
    
    def _register_component(self, comp_type: Type, entity: Entity):
        if comp_type not in self.component_index:
            self.component_index[comp_type] = set()
        self.component_index[comp_type].add(entity.id)
    
    def _unregister_component(self, comp_type: Type, entity_id: int):
        if comp_type in self.component_index:
            self.component_index[comp_type].discard(entity_id)
            if not self.component_index[comp_type]:
                del self.component_index[comp_type]
    
    def _unregister_entity_components(self, entity: Entity):
        for comp_type in list(entity.components.keys()):
            self._unregister_component(comp_type, entity.id)

class System:
    """Base class for all systems."""
    priority = 0  # Lower runs first
    
    def __init__(self):
        self.world: Optional[World] = None
        self.active = True
    
    def update(self, dt: float):
        raise NotImplementedError

# ============================================================================
# COMPONENTS (Pure Data)
# ============================================================================

@dataclass
class PositionComponent:
    x: float = 0.0
    y: float = 0.0

@dataclass
class VelocityComponent:
    dx: float = 0.0
    dy: float = 0.0
    speed: float = 0.0

@dataclass 
class SizeComponent:
    width: float = 30.0
    height: float = 30.0
    hitbox_margin: float = 0.0

@dataclass
class PlayerComponent:
    player_id: int = 1
    wood: int = 0
    coins: int = 0
    last_direction_x: float = 0.0
    last_direction_y: float = 1.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0

@dataclass
class InputComponent:
    move_x: int = 0
    move_y: int = 0
    shoot_x: int = 0
    shoot_y: int = 0
    harvest_pressed: bool = False
    build_pressed: bool = False
    interact_pressed: bool = False

@dataclass
class EnemyComponent:
    enemy_id: int = 0
    stuck_timer: float = 0.0
    last_x: float = 0.0
    last_y: float = 0.0

@dataclass
class ProjectileComponent:
    owner_id: int = 1
    network_sent: bool = False

@dataclass
class TreeComponent:
    tree_id: int = 0
    is_chopped: bool = False
    chop_progress: float = 0.0
    current_chopper: Optional[int] = None

@dataclass
class RockComponent:
    rock_id: int = 0

@dataclass
class WallComponent:
    owner_id: Optional[int] = None
    is_solid: bool = False

@dataclass
class DoorComponent:
    owner_id: Optional[int] = None
    is_open: bool = False
    is_blocking: bool = False  # Like walls, starts non-blocking when built

@dataclass
class StairsComponent:
    owner_id: Optional[int] = None
    direction_x: float = 0.0  # Direction towards higher level
    direction_y: float = 0.0
    from_level: int = 0  # Level stairs start from
    to_level: int = 1    # Level stairs go to

@dataclass
class HeightComponent:
    level: int = 0  # Height level (0 = ground, 1+ = higher)

@dataclass
class CollisionComponent:
    layer: str = "default"  # "player", "enemy", "projectile", "obstacle"
    collides_with: List[str] = field(default_factory=list)

@dataclass
class HealthComponent:
    current: float = 100.0
    max_health: float = 100.0
    regen_rate: float = 0.0
    regen_delay: float = 0.0
    last_damage_time: float = 0.0

class SpriteComponent:
    """Component for visual representation - holds pyglet shapes/sprites."""
    def __init__(self):
        self.shapes: List[Any] = []
        self.sprite: Optional[pyglet.sprite.Sprite] = None
        self.visible: bool = True
        self.progress_bar_bg: Optional[Any] = None
        self.progress_bar_fg: Optional[Any] = None
    
    def add_shape(self, shape):
        self.shapes.append(shape)
    
    def cleanup(self):
        for shape in self.shapes:
            try:
                shape.delete()
            except:
                pass
        self.shapes.clear()
        if self.sprite:
            try:
                self.sprite.delete()
            except:
                pass
        if self.progress_bar_bg:
            try:
                self.progress_bar_bg.delete()
            except:
                pass
        if self.progress_bar_fg:
            try:
                self.progress_bar_fg.delete()
            except:
                pass

@dataclass
class TagComponent:
    """Simple tag for entity identification."""
    tags: Set[str] = field(default_factory=set)

# ============================================================================
# CONSTANTS
# ============================================================================

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60
NETWORK_PORT = 5555

WORLD_WIDTH = 4000
WORLD_HEIGHT = 3000

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
CYAN = (0, 255, 255)
BLUE = (100, 150, 255)
YELLOW = (255, 255, 0)
ORANGE = (255, 165, 0)

PLAYER_SIZE = 30
PLAYER_HITBOX_MARGIN = 4
PLAYER_SPEED = 150

PROJECTILE_SIZE = 10
PROJECTILE_SPEED = 10
PROJECTILE_FIRE_RATE = 0.5

ENEMY_SIZE = 25
ENEMY_SPEED = 2
INITIAL_ENEMY_SPAWN_RATE = 60
MIN_ENEMY_SPAWN_RATE = 10
MAX_ENEMIES = 150
ENEMY_SPAWN_ACCELERATION = 0.5
ENEMY_PATHFINDING_RANGE = 50

DAY_LENGTH = 60.0
NIGHT_LENGTH = 45.0
NIGHT_SPAWN_MULTIPLIER_BASE = 1.5
NIGHT_SPAWN_MULTIPLIER_PER_DAY = 0.3
NIGHT_MAX_ENEMIES_BASE = 300
NIGHT_MAX_ENEMIES_PER_DAY = 10

ROCK_MIN_SIZE = 40
ROCK_MAX_SIZE = 120
MAX_ROCKS = 50

TREE_SIZE = 25
MAX_TREES = 80
TREE_CHOP_TIME = 1.5
HARVEST_RANGE = 60

WALL_WOOD_COST = 1
GRID_SIZE = PLAYER_SIZE
WALL_SIZE = GRID_SIZE
CORNER_SLIDE_THRESHOLD = 8

# ============================================================================
# CAMERA
# ============================================================================

class Camera:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.target_x = 0
        self.target_y = 0
        self.first_update = True
    
    def update(self, target_x, target_y):
        self.target_x = target_x - SCREEN_WIDTH // 2
        self.target_y = target_y - SCREEN_HEIGHT // 2
        
        if self.first_update:
            self.x = self.target_x
            self.y = self.target_y
            self.first_update = False
        else:
            self.x += (self.target_x - self.x) * 0.1
            self.y += (self.target_y - self.y) * 0.1
        
        self.x = max(0, min(WORLD_WIDTH - SCREEN_WIDTH, self.x))
        self.y = max(0, min(WORLD_HEIGHT - SCREEN_HEIGHT, self.y))
    
    def world_to_screen(self, world_x, world_y):
        return (world_x - self.x, world_y - self.y)
    
    def screen_to_world(self, screen_x, screen_y):
        return (screen_x + self.x, screen_y + self.y)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def check_collision(rect1, rect2):
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2
    return (x1 < x2 + w2 and x1 + w1 > x2 and
            y1 < y2 + h2 and y1 + h1 > y2)

def snap_to_grid(x, y):
    grid_x = (x // GRID_SIZE) * GRID_SIZE + GRID_SIZE // 2
    grid_y = (y // GRID_SIZE) * GRID_SIZE + GRID_SIZE // 2
    return grid_x, grid_y

def get_entity_rect(entity: Entity):
    """Get collision rectangle for an entity. Returns (x, y, width, height) where x,y is top-left."""
    pos = entity.get_component(PositionComponent)
    size = entity.get_component(SizeComponent)
    if pos and size:
        margin = size.hitbox_margin
        # Check if entity uses center position (trees, walls)
        tree = entity.get_component(TreeComponent)
        wall = entity.get_component(WallComponent)
        if tree or wall:
            # Position is center, convert to top-left
            top_left_x = pos.x - size.width / 2
            top_left_y = pos.y - size.height / 2
            # Apply margin after conversion
            return (top_left_x + margin, top_left_y + margin, 
                    size.width - margin * 2, size.height - margin * 2)
        else:
            # Position is top-left
            return (pos.x + margin, pos.y + margin, 
                    size.width - margin * 2, size.height - margin * 2)
    return None

def get_entity_center(entity: Entity):
    """Get center position of an entity."""
    pos = entity.get_component(PositionComponent)
    size = entity.get_component(SizeComponent)
    if pos and size:
        # Check if entity uses center position (trees, walls)
        tree = entity.get_component(TreeComponent)
        wall = entity.get_component(WallComponent)
        if tree or wall:
            # Position is already center
            return (pos.x, pos.y)
        else:
            # Position is top-left, calculate center
            return (pos.x + size.width / 2, pos.y + size.height / 2)
    elif pos:
        return (pos.x, pos.y)
    return (0, 0)

def gather_world_obstacles(world: World) -> List[Entity]:
    """Fallback for when spatial partitioning isn't available."""
    obstacles = []
    for entity in world.get_entities_with(PositionComponent, SizeComponent, CollisionComponent):
        coll = entity.get_component(CollisionComponent)
        if coll.layer != "obstacle":
            continue
        tree = entity.get_component(TreeComponent)
        if tree and tree.is_chopped:
            continue
        wall = entity.get_component(WallComponent)
        if wall and not wall.is_solid:
            continue
        door = entity.get_component(DoorComponent)
        if door:
            # Doors only block if they're closed AND blocking (player has moved away)
            if door.is_open or not door.is_blocking:
                continue
        obstacles.append(entity)
    return obstacles

# ============================================================================
# SPATIAL PARTITIONING (QUADTREE)
# ============================================================================

class QuadTree:
    """Simple quadtree for spatial partitioning."""
    def __init__(self, bounds, level=0, max_objects=8, max_levels=6):
        self.bounds = bounds  # (x, y, width, height)
        self.level = level
        self.max_objects = max_objects
        self.max_levels = max_levels
        self.objects: List[tuple] = []  # (rect, entity_id)
        self.nodes: List['QuadTree'] = []
    
    def clear(self):
        self.objects.clear()
        for node in self.nodes:
            node.clear()
        self.nodes = []
    
    def split(self):
        x, y, w, h = self.bounds
        half_w = w / 2
        half_h = h / 2
        next_level = self.level + 1
        self.nodes = [
            QuadTree((x, y, half_w, half_h), next_level, self.max_objects, self.max_levels),  # Top-left
            QuadTree((x + half_w, y, half_w, half_h), next_level, self.max_objects, self.max_levels),  # Top-right
            QuadTree((x, y + half_h, half_w, half_h), next_level, self.max_objects, self.max_levels),  # Bottom-left
            QuadTree((x + half_w, y + half_h, half_w, half_h), next_level, self.max_objects, self.max_levels),  # Bottom-right
        ]
    
    def _rect_fits(self, rect, bounds):
        rx, ry, rw, rh = rect
        bx, by, bw, bh = bounds
        return (rx >= bx and ry >= by and
                rx + rw <= bx + bw and
                ry + rh <= by + bh)
    
    def insert(self, rect, entity_id):
        if self.nodes:
            for idx, node in enumerate(self.nodes):
                if self._rect_fits(rect, node.bounds):
                    node.insert(rect, entity_id)
                    return
        
        self.objects.append((rect, entity_id))
        
        if (len(self.objects) > self.max_objects) and (self.level < self.max_levels):
            if not self.nodes:
                self.split()
            i = 0
            while i < len(self.objects):
                moved = False
                for node in self.nodes:
                    if self._rect_fits(self.objects[i][0], node.bounds):
                        rect_to_move, ent_id = self.objects.pop(i)
                        node.insert(rect_to_move, ent_id)
                        moved = True
                        break
                if not moved:
                    i += 1
    
    def retrieve(self, rect, results=None):
        if results is None:
            results = set()
        
        # Check objects in this node
        for obj_rect, entity_id in self.objects:
            if check_collision(rect, obj_rect):
                results.add(entity_id)
        
        # Check child nodes if they exist and bounds intersect
        for node in self.nodes:
            if check_collision(rect, node.bounds):
                node.retrieve(rect, results)
        
        return results


class SpatialPartition:
    """Manages quadtrees for different entity categories."""
    def __init__(self, width, height):
        bounds = (0, 0, width, height)
        self.trees = {
            'obstacles': QuadTree(bounds),
            'enemies': QuadTree(bounds),
            'projectiles': QuadTree(bounds),
            'players': QuadTree(bounds),
        }
    
    def clear_all(self):
        for tree in self.trees.values():
            tree.clear()
    
    def update_category(self, category, entities: List[Entity]):
        tree = self.trees.get(category)
        if not tree:
            return
        tree.clear()
        for entity in entities:
            rect = get_entity_rect(entity)
            if rect:
                tree.insert(rect, entity.id)
    
    def query(self, category, rect):
        tree = self.trees.get(category)
        if not tree:
            return set()
        return tree.retrieve(rect, set())

# ============================================================================
# RENDER RESOURCE MANAGER
# ============================================================================

class RenderResourceManager:
    """Caches procedural textures so sprites can share image data."""
    def __init__(self):
        self.cache: Dict[Any, pyglet.image.ImageData] = {}
    
    def get_enemy_image(self):
        key = ('enemy', ENEMY_SIZE)
        if key not in self.cache:
            self.cache[key] = self._create_bordered_square_image(
                ENEMY_SIZE,
                fill_color=RED,
                border_color=WHITE,
                border_thickness=2
            )
        return self.cache[key]
    
    def get_projectile_image(self):
        key = ('projectile', PROJECTILE_SIZE)
        if key not in self.cache:
            self.cache[key] = self._create_radial_gradient_image(
                PROJECTILE_SIZE,
                inner_color=(255, 255, 200, 255),
                outer_color=(255, 180, 30, 30)
            )
        return self.cache[key]
    
    def get_wall_image(self):
        key = ('wall', WALL_SIZE)
        if key not in self.cache:
            self.cache[key] = self._create_bordered_square_image(
                WALL_SIZE,
                fill_color=(139, 90, 43),
                border_color=(101, 67, 33),
                border_thickness=2
            )
        return self.cache[key]
    
    def _create_bordered_square_image(self, size, fill_color, border_color, border_thickness):
        data = bytearray(size * size * 4)
        for y in range(size):
            for x in range(size):
                if (x < border_thickness or y < border_thickness or
                        x >= size - border_thickness or y >= size - border_thickness):
                    color = border_color
                else:
                    color = fill_color
                idx = (y * size + x) * 4
                data[idx] = color[0]
                data[idx + 1] = color[1]
                data[idx + 2] = color[2]
                data[idx + 3] = 255
        return pyglet.image.ImageData(size, size, 'RGBA', bytes(data))
    
    def _create_radial_gradient_image(self, size, inner_color, outer_color):
        data = bytearray(size * size * 4)
        center = (size - 1) / 2
        max_dist = math.sqrt(2 * (center ** 2))
        for y in range(size):
            for x in range(size):
                dx = x - center
                dy = y - center
                t = min(math.sqrt(dx * dx + dy * dy) / max_dist, 1.0)
                idx = (y * size + x) * 4
                data[idx] = int(inner_color[0] * (1 - t) + outer_color[0] * t)
                data[idx + 1] = int(inner_color[1] * (1 - t) + outer_color[1] * t)
                data[idx + 2] = int(inner_color[2] * (1 - t) + outer_color[2] * t)
                data[idx + 3] = int(inner_color[3] * (1 - t) + outer_color[3] * t)
        return pyglet.image.ImageData(size, size, 'RGBA', bytes(data))

# ============================================================================
# SCREEN MANAGER
# ============================================================================

class ScreenManager:
    current_window = None
    
    @classmethod
    def set_window(cls, window):
        if cls.current_window is not None and cls.current_window != window:
            try:
                cls.current_window.close()
            except:
                pass
        cls.current_window = window
    
    @classmethod
    def get_window(cls):
        return cls.current_window

# ============================================================================
# SYSTEMS
# ============================================================================

class InputSystem(System):
    """Handles player input and updates InputComponent."""
    priority = 0
    
    def __init__(self, keys, arrow_keys_pressed):
        super().__init__()
        self.keys = keys
        self.arrow_keys_pressed = arrow_keys_pressed
    
    def update(self, dt: float):
        for entity in self.world.get_entities_with(PlayerComponent, InputComponent):
            input_comp = entity.get_component(InputComponent)
            
            # Movement input (WASD)
            input_comp.move_x = 0
            input_comp.move_y = 0
            if self.keys[pyglet.window.key.W]:
                input_comp.move_y += 1
            if self.keys[pyglet.window.key.S]:
                input_comp.move_y -= 1
            if self.keys[pyglet.window.key.A]:
                input_comp.move_x -= 1
            if self.keys[pyglet.window.key.D]:
                input_comp.move_x += 1
            
            # Shooting input (Arrow keys)
            input_comp.shoot_x = 0
            input_comp.shoot_y = 0
            if self.arrow_keys_pressed.get(pyglet.window.key.UP, False):
                input_comp.shoot_y = 1
            elif self.arrow_keys_pressed.get(pyglet.window.key.DOWN, False):
                input_comp.shoot_y = -1
            if self.arrow_keys_pressed.get(pyglet.window.key.LEFT, False):
                input_comp.shoot_x = -1
            elif self.arrow_keys_pressed.get(pyglet.window.key.RIGHT, False):
                input_comp.shoot_x = 1
            
            # Harvest input
            input_comp.harvest_pressed = self.keys[pyglet.window.key.SPACE]
            
            # Interact input (spacebar also used for interaction)
            input_comp.interact_pressed = self.keys[pyglet.window.key.SPACE]


class SpatialPartitionSystem(System):
    """Populates quadtrees for fast spatial queries."""
    priority = 5
    
    def update(self, dt: float):
        if not self.world.spatial:
            return
        
        spatial = self.world.spatial
        spatial.clear_all()
        
        # Obstacles (rocks, unchopped trees, solid walls, closed doors)
        obstacles = []
        for entity in self.world.get_entities_with(PositionComponent, SizeComponent, CollisionComponent):
            coll = entity.get_component(CollisionComponent)
            if coll.layer != "obstacle":
                continue
            tree = entity.get_component(TreeComponent)
            if tree and tree.is_chopped:
                continue
            wall = entity.get_component(WallComponent)
            if wall and not wall.is_solid:
                continue
            door = entity.get_component(DoorComponent)
            if door:
                # Doors only block if they're closed AND blocking (player has moved away)
                if door.is_open or not door.is_blocking:
                    continue
            obstacles.append(entity)
        spatial.update_category('obstacles', obstacles)
        
        # Dynamic categories
        spatial.update_category('enemies', self.world.get_entities_with(EnemyComponent, PositionComponent, SizeComponent))
        spatial.update_category('projectiles', self.world.get_entities_with(ProjectileComponent, PositionComponent, SizeComponent))
        spatial.update_category('players', self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent))


class MovementSystem(System):
    """Handles movement with collision detection."""
    priority = 10
    
    def update(self, dt: float):
        for entity in self.world.get_entities_with(PlayerComponent, PositionComponent, InputComponent, VelocityComponent, SizeComponent):
            self._move_player(entity, dt)
    
    def _move_player(self, entity: Entity, dt: float):
        pos = entity.get_component(PositionComponent)
        input_comp = entity.get_component(InputComponent)
        vel = entity.get_component(VelocityComponent)
        size = entity.get_component(SizeComponent)
        player = entity.get_component(PlayerComponent)
        
        old_x, old_y = pos.x, pos.y
        
        # Normalize movement vector so diagonal movement is same speed
        move_x = input_comp.move_x
        move_y = input_comp.move_y
        move_length = math.sqrt(move_x**2 + move_y**2)
        if move_length > 0:
            move_x = move_x / move_length
            move_y = move_y / move_length
        
        new_x = pos.x + move_x * vel.speed * dt
        new_y = pos.y + move_y * vel.speed * dt
        
        margin = size.hitbox_margin
        hitbox_size = size.width - margin * 2
        
        # Check if player is already colliding (shouldn't happen, but safety check)
        current_player_rect = (old_x + margin, old_y + margin, hitbox_size, hitbox_size)
        
        can_move_x = True
        can_move_y = True
        blocking_obstacle = None
        
        obstacles = []
        if self.world.spatial:
            query_margin = size.width * 2
            query_rect = (
                new_x - query_margin,
                new_y - query_margin,
                size.width + query_margin * 2,
                size.height + query_margin * 2
            )
            for entity_id in self.world.spatial.query('obstacles', query_rect):
                obstacle = self.world.get_entity(entity_id)
                if obstacle:
                    obstacles.append(obstacle)
        else:
            obstacles = gather_world_obstacles(self.world)
        
        # Use consistent player hitbox for all collision checks
        player_rect_new = (new_x + margin, new_y + margin, hitbox_size, hitbox_size)
        player_rect_old = (old_x + margin, old_y + margin, hitbox_size, hitbox_size)
        
        for obs in obstacles:
            obs_rect = get_entity_rect(obs)
            if not obs_rect:
                continue
            
            # Check collision with new position
            if check_collision(player_rect_new, obs_rect):
                blocking_obstacle = obs
                # Test X-only and Y-only movement separately
                test_x_rect = (new_x + margin, old_y + margin, hitbox_size, hitbox_size)
                test_y_rect = (old_x + margin, new_y + margin, hitbox_size, hitbox_size)
                
                if check_collision(test_x_rect, obs_rect):
                    can_move_x = False
                if check_collision(test_y_rect, obs_rect):
                    can_move_y = False
                
                # If both directions blocked, don't check other obstacles
                if not can_move_x and not can_move_y:
                    break
        
        # Improved corner sliding - only slide if very close to edge
        if blocking_obstacle and (not can_move_x or not can_move_y):
            obs_rect = get_entity_rect(blocking_obstacle)
            if not obs_rect:
                obs_rect = (0, 0, 0, 0)
            
            # Use hitbox centers for more accurate sliding
            player_hitbox_center_x = old_x + margin + hitbox_size / 2
            player_hitbox_center_y = old_y + margin + hitbox_size / 2
            obs_center_x = obs_rect[0] + obs_rect[2] / 2
            obs_center_y = obs_rect[1] + obs_rect[3] / 2
            
            # Only slide if we're very close to an edge (reduces edge catching)
            slide_threshold = CORNER_SLIDE_THRESHOLD
            
            if input_comp.move_x != 0 and not can_move_x and can_move_y:
                # Check distance to top and bottom edges of obstacle
                top_edge_y = obs_rect[1] + obs_rect[3]
                bot_edge_y = obs_rect[1]
                top_dist = abs(player_hitbox_center_y - top_edge_y)
                bot_dist = abs(player_hitbox_center_y - bot_edge_y)
                
                # Only slide if within threshold
                if top_dist < slide_threshold:
                    slide_y = vel.speed * dt * 0.3  # Reduced slide speed
                    # Re-check collision after slide
                    test_slide_rect = (new_x + margin, old_y + margin + slide_y, hitbox_size, hitbox_size)
                    if not any(check_collision(test_slide_rect, get_entity_rect(o)) for o in obstacles if o != blocking_obstacle):
                        new_y += slide_y
                elif bot_dist < slide_threshold:
                    slide_y = -vel.speed * dt * 0.3
                    test_slide_rect = (new_x + margin, old_y + margin + slide_y, hitbox_size, hitbox_size)
                    if not any(check_collision(test_slide_rect, get_entity_rect(o)) for o in obstacles if o != blocking_obstacle):
                        new_y += slide_y
            
            if input_comp.move_y != 0 and not can_move_y and can_move_x:
                # Check distance to left and right edges of obstacle
                right_edge_x = obs_rect[0] + obs_rect[2]
                left_edge_x = obs_rect[0]
                right_dist = abs(player_hitbox_center_x - right_edge_x)
                left_dist = abs(player_hitbox_center_x - left_edge_x)
                
                # Only slide if within threshold
                if right_dist < slide_threshold:
                    slide_x = vel.speed * dt * 0.3
                    test_slide_rect = (old_x + margin + slide_x, new_y + margin, hitbox_size, hitbox_size)
                    if not any(check_collision(test_slide_rect, get_entity_rect(o)) for o in obstacles if o != blocking_obstacle):
                        new_x += slide_x
                elif left_dist < slide_threshold:
                    slide_x = -vel.speed * dt * 0.3
                    test_slide_rect = (old_x + margin + slide_x, new_y + margin, hitbox_size, hitbox_size)
                    if not any(check_collision(test_slide_rect, get_entity_rect(o)) for o in obstacles if o != blocking_obstacle):
                        new_x += slide_x
        
        # Calculate velocity for projectile inheritance
        if dt > 0:
            player.velocity_x = (new_x - old_x) / dt if can_move_x else 0
            player.velocity_y = (new_y - old_y) / dt if can_move_y else 0
        
        # Apply movement - but verify final position doesn't cause collision
        final_x = new_x if can_move_x else old_x
        final_y = new_y if can_move_y else old_y
        final_player_rect = (final_x + margin, final_y + margin, hitbox_size, hitbox_size)
        
        # Double-check no collision at final position (prevents clipping)
        for obs in obstacles:
            obs_rect = get_entity_rect(obs)
            if obs_rect and check_collision(final_player_rect, obs_rect):
                # If we'd collide, revert to old position
                final_x = old_x
                final_y = old_y
                break
        
        pos.x = final_x
        pos.y = final_y
        
        # Update direction
        if input_comp.move_x != 0 or input_comp.move_y != 0:
            player.last_direction_x = input_comp.move_x
            player.last_direction_y = input_comp.move_y
        
        # Keep in world bounds
        pos.x = max(size.width // 2, min(WORLD_WIDTH - size.width // 2, pos.x))
        pos.y = max(size.height // 2, min(WORLD_HEIGHT - size.height // 2, pos.y))


class EnemyAISystem(System):
    """Handles enemy AI pathfinding and movement."""
    priority = 15
    
    def update(self, dt: float):
        # Get player position
        player_entity = None
        for entity in self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent):
            player_entity = entity
            break

        if not player_entity:
            return
        
        player_pos = player_entity.get_component(PositionComponent)
        player_size = player_entity.get_component(SizeComponent)
        player_x = player_pos.x + player_size.width / 2
        player_y = player_pos.y + player_size.height / 2
        
        # Update each enemy
        for entity in self.world.get_entities_with(EnemyComponent, PositionComponent, VelocityComponent, SizeComponent):
            self._update_enemy(entity, player_x, player_y, dt)
    
    def _get_nearby_obstacles(self, rect):
        if self.world.spatial:
            obstacles = []
            ids = self.world.spatial.query('obstacles', rect)
            for entity_id in ids:
                obstacle = self.world.get_entity(entity_id)
                if obstacle:
                    obstacles.append(obstacle)
            return obstacles
        return gather_world_obstacles(self.world)
    
    def _get_nearby_enemies(self, rect, exclude_entity_id):
        """Get nearby enemies excluding the current entity."""
        if self.world.spatial:
            enemies = []
            ids = self.world.spatial.query('enemies', rect)
            for entity_id in ids:
                if entity_id != exclude_entity_id:
                    enemy = self.world.get_entity(entity_id)
                    if enemy:
                        enemies.append(enemy)
            return enemies
        # Fallback: get all enemies
        enemies = []
        for e in self.world.get_entities_with(EnemyComponent, PositionComponent, SizeComponent):
            if e.id != exclude_entity_id:
                enemies.append(e)
        return enemies
    
    def _update_enemy(self, entity: Entity, player_x: float, player_y: float, dt: float):
        pos = entity.get_component(PositionComponent)
        vel = entity.get_component(VelocityComponent)
        size = entity.get_component(SizeComponent)
        enemy = entity.get_component(EnemyComponent)
        entity_rect = (pos.x - ENEMY_PATHFINDING_RANGE, pos.y - ENEMY_PATHFINDING_RANGE,
                       size.width + ENEMY_PATHFINDING_RANGE * 2, size.height + ENEMY_PATHFINDING_RANGE * 2)
        obstacles = self._get_nearby_obstacles(entity_rect)
        
        # Get nearby enemies for collision
        nearby_enemies = self._get_nearby_enemies(entity_rect, entity.id)
        
        # Find path around obstacles
        dir_x, dir_y = self._find_path(pos.x, pos.y, player_x, player_y, size.width, obstacles)
        
        speed_per_frame = vel.speed * dt * 60
        new_x = pos.x + dir_x * speed_per_frame
        new_y = pos.y + dir_y * speed_per_frame
        
        old_x, old_y = pos.x, pos.y
        
        # Check collision with obstacles
        enemy_rect = (new_x, new_y, size.width, size.height)
        can_move_x = True
        can_move_y = True
        
        for obs in obstacles:
            obs_rect = get_entity_rect(obs)
            if not obs_rect:
                continue
            
            if check_collision(enemy_rect, obs_rect):
                test_x = (new_x, old_y, size.width, size.height)
                test_y = (old_x, new_y, size.width, size.height)
                
                if check_collision(test_x, obs_rect):
                    can_move_x = False
                if check_collision(test_y, obs_rect):
                    can_move_y = False
        
        # Check collision with other enemies
        for other_enemy in nearby_enemies:
            other_pos = other_enemy.get_component(PositionComponent)
            other_size = other_enemy.get_component(SizeComponent)
            other_rect = (other_pos.x, other_pos.y, other_size.width, other_size.height)
            
            if check_collision(enemy_rect, other_rect):
                test_x = (new_x, old_y, size.width, size.height)
                test_y = (old_x, new_y, size.width, size.height)
                
                if check_collision(test_x, other_rect):
                    can_move_x = False
                if check_collision(test_y, other_rect):
                    can_move_y = False
        
        # Try perpendicular movement if blocked
        if not can_move_x and not can_move_y:
            perp_x, perp_y = -dir_y, dir_x
            test_new_x = pos.x + perp_x * speed_per_frame
            test_new_y = pos.y + perp_y * speed_per_frame
            test_rect = (test_new_x, test_new_y, size.width, size.height)
            
            can_move_perp = True
            for obs in obstacles:
                obs_rect = get_entity_rect(obs)
                if not obs_rect:
                    continue
                if check_collision(test_rect, obs_rect):
                    can_move_perp = False
                    break
            
            # Also check perpendicular movement against other enemies
            if can_move_perp:
                for other_enemy in nearby_enemies:
                    other_pos = other_enemy.get_component(PositionComponent)
                    other_size = other_enemy.get_component(SizeComponent)
                    other_rect = (other_pos.x, other_pos.y, other_size.width, other_size.height)
                    if check_collision(test_rect, other_rect):
                        can_move_perp = False
                        break
            
            if can_move_perp:
                pos.x = test_new_x
                pos.y = test_new_y
        else:
            if can_move_x:
                pos.x = new_x
            if can_move_y:
                pos.y = new_y
    
    def _find_path(self, x, y, target_x, target_y, size, obstacles):
        dx = target_x - x
        dy = target_y - y
        distance = math.sqrt(dx**2 + dy**2)
        
        if distance == 0:
            return (0, 0)
        
        dir_x = dx / distance
        dir_y = dy / distance
        
        look_ahead = ENEMY_PATHFINDING_RANGE
        check_x = x + dir_x * look_ahead
        check_y = y + dir_y * look_ahead
        check_rect = (check_x - size/2, check_y - size/2, size, size)
        
        blocking = None
        for obs in obstacles:
            obs_rect = get_entity_rect(obs)
            if not obs_rect:
                continue
            if check_collision(check_rect, obs_rect):
                blocking = obs
                break
        
        if not blocking:
            return (dir_x, dir_y)
        
        # Steer around obstacle
        obs_center_x, obs_center_y = get_entity_center(blocking)
        obs_size_comp = blocking.get_component(SizeComponent)
        
        avoid_dx = x - obs_center_x
        avoid_dy = y - obs_center_y
        avoid_dist = math.sqrt(avoid_dx**2 + avoid_dy**2)
        
        if avoid_dist > 0:
            avoid_dx /= avoid_dist
            avoid_dy /= avoid_dist
            
            obstacle_size = max(obs_size_comp.width, obs_size_comp.height) if obs_size_comp else size
            avoid_strength = max(0, 1.0 - (avoid_dist / (obstacle_size + size)))
            
            steer_x = dir_x * (1.0 - avoid_strength) + avoid_dx * avoid_strength
            steer_y = dir_y * (1.0 - avoid_strength) + avoid_dy * avoid_strength
            
            steer_len = math.sqrt(steer_x**2 + steer_y**2)
            if steer_len > 0:
                steer_x /= steer_len
                steer_y /= steer_len
            
            return (steer_x, steer_y)
        
        return (dir_x, dir_y)
    

class ProjectileSystem(System):
    """Handles projectile movement and cleanup."""
    priority = 20
    
    def update(self, dt: float):
        for entity in self.world.get_entities_with(ProjectileComponent, PositionComponent, VelocityComponent):
            pos = entity.get_component(PositionComponent)
            vel = entity.get_component(VelocityComponent)
            
            pos.x += vel.dx
            pos.y += vel.dy
            
            # Remove if off-world
            if (pos.x < -PROJECTILE_SIZE or pos.x > WORLD_WIDTH + PROJECTILE_SIZE or
                pos.y < -PROJECTILE_SIZE or pos.y > WORLD_HEIGHT + PROJECTILE_SIZE):
                self.world.remove_entity(entity.id)


class CollisionSystem(System):
    """Handles collision detection and responses."""
    priority = 30
    
    def __init__(self, game_window):
        super().__init__()
        self.game_window = game_window
    
    def update(self, dt: float):
        projectiles = list(self.world.get_entities_with(ProjectileComponent, PositionComponent, SizeComponent))
        enemies = list(self.world.get_entities_with(EnemyComponent, PositionComponent, SizeComponent))
        players = list(self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent))
        spatial = self.world.spatial
        fallback_obstacles = gather_world_obstacles(self.world) if not spatial else []
        
        projectiles_to_remove = set()
        enemies_to_remove = set()
        
        # Projectile vs Enemy
        for proj in projectiles:
            proj_pos = proj.get_component(PositionComponent)
            proj_size = proj.get_component(SizeComponent)
            proj_rect = (proj_pos.x, proj_pos.y, proj_size.width, proj_size.height)
            if spatial:
                enemy_ids = spatial.query('enemies', proj_rect)
                nearby_enemies = []
                for entity_id in enemy_ids:
                    enemy_entity = self.world.get_entity(entity_id)
                    if enemy_entity:
                        nearby_enemies.append(enemy_entity)
            else:
                nearby_enemies = enemies
            
            for enemy in nearby_enemies:
                enemy_pos = enemy.get_component(PositionComponent)
                enemy_size = enemy.get_component(SizeComponent)
                enemy_rect = (enemy_pos.x, enemy_pos.y, enemy_size.width, enemy_size.height)
                
                if check_collision(proj_rect, enemy_rect):
                    # Check height: player can only shoot enemies if player is exactly 1 level higher
                    proj_owner = proj.get_component(ProjectileComponent)
                    if proj_owner and proj_owner.owner_id:
                        # Find player who shot
                        shooter_height = None
                        for player in players:
                            player_comp = player.get_component(PlayerComponent)
                            if player_comp.player_id == proj_owner.owner_id:
                                shooter_height = player.get_component(HeightComponent)
                                break
                        
                        if shooter_height:
                            enemy_height = enemy.get_component(HeightComponent)
                            if enemy_height and shooter_height.level - enemy_height.level == 1:
                                projectiles_to_remove.add(proj.id)
                                enemies_to_remove.add(enemy.id)
                                # Award coins to player
                                if players:
                                    player_comp = players[0].get_component(PlayerComponent)
                                    player_comp.coins += 1
                        else:
                            # No height check if shooter not found (fallback)
                            projectiles_to_remove.add(proj.id)
                            enemies_to_remove.add(enemy.id)
                            if players:
                                player_comp = players[0].get_component(PlayerComponent)
                                player_comp.coins += 1
                    else:
                        # No owner info, allow hit (fallback)
                        projectiles_to_remove.add(proj.id)
                        enemies_to_remove.add(enemy.id)
                        if players:
                            player_comp = players[0].get_component(PlayerComponent)
                            player_comp.coins += 1
        
        # Projectile vs Obstacles
        for proj in projectiles:
            if proj.id in projectiles_to_remove:
                continue
            proj_pos = proj.get_component(PositionComponent)
            proj_size = proj.get_component(SizeComponent)
            proj_rect = (proj_pos.x, proj_pos.y, proj_size.width, proj_size.height)
            nearby_obstacles = fallback_obstacles
            if spatial:
                ids = spatial.query('obstacles', proj_rect)
                nearby_obstacles = []
                for entity_id in ids:
                    obstacle = self.world.get_entity(entity_id)
                    if obstacle:
                        nearby_obstacles.append(obstacle)
            
            for obs in nearby_obstacles:
                obs_rect = get_entity_rect(obs)
                if obs_rect and check_collision(proj_rect, obs_rect):
                    projectiles_to_remove.add(proj.id)
                break
                    
        # Enemy vs Player
        for player in players:
            player_pos = player.get_component(PositionComponent)
            player_size = player.get_component(SizeComponent)
            margin = player_size.hitbox_margin
            player_rect = (player_pos.x + margin, player_pos.y + margin,
                          player_size.width - margin * 2, player_size.height - margin * 2)
            
            if spatial:
                enemy_ids = spatial.query('enemies', player_rect)
                nearby_enemies = []
                for entity_id in enemy_ids:
                    enemy_entity = self.world.get_entity(entity_id)
                    if enemy_entity:
                        nearby_enemies.append(enemy_entity)
            else:
                nearby_enemies = enemies
            
            for enemy in nearby_enemies:
                if enemy.id in enemies_to_remove:
                    continue
                enemy_pos = enemy.get_component(PositionComponent)
                enemy_size = enemy.get_component(SizeComponent)
                enemy_rect = (enemy_pos.x, enemy_pos.y, enemy_size.width, enemy_size.height)
                
                if check_collision(player_rect, enemy_rect):
                    # Check height: enemies can't hurt players that are higher than them
                    player_height = player.get_component(HeightComponent)
                    enemy_height = enemy.get_component(HeightComponent)
                    
                    if player_height and enemy_height:
                        if player_height.level > enemy_height.level:
                            continue  # Player is higher, enemy can't hurt
                    
                    # Game over
                    if self.game_window:
                        self.game_window.show_game_over()
                    return
        
        # Remove entities
        for entity_id in projectiles_to_remove:
            self.world.remove_entity(entity_id)
        for entity_id in enemies_to_remove:
            self.world.remove_entity(entity_id)


class InteractionSystem(System):
    """Handles door interactions."""
    priority = 24
    
    def __init__(self, game_window):
        super().__init__()
        self.game_window = game_window
        self.interact_range = 60  # Same as harvest range
        self.nearby_door = None
        self.tooltip_text = None
        self.last_interact_pressed = False  # Track previous frame's state for edge detection
    
    def update(self, dt: float):
        # Get player
        player_entity = None
        for entity in self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent, InputComponent):
            player_entity = entity
            break
        
        if not player_entity:
            self.nearby_door = None
            if self.tooltip_text:
                self.tooltip_text.visible = False
            return
        
        player_pos = player_entity.get_component(PositionComponent)
        player_size = player_entity.get_component(SizeComponent)
        input_comp = player_entity.get_component(InputComponent)
        
        player_center_x = player_pos.x + player_size.width / 2
        player_center_y = player_pos.y + player_size.height / 2
        
        # Find nearby door
        nearby_door = None
        min_dist = float('inf')
        
        for entity in self.world.get_entities_with(DoorComponent, PositionComponent, SizeComponent):
            door_pos = entity.get_component(PositionComponent)
            door_center_x = door_pos.x
            door_center_y = door_pos.y
            
            dx = player_center_x - door_center_x
            dy = player_center_y - door_center_y
            distance = math.sqrt(dx**2 + dy**2)
            
            if distance <= self.interact_range and distance < min_dist:
                min_dist = distance
                nearby_door = entity
        
        self.nearby_door = nearby_door
        
        # Handle interaction - only on edge (press, not hold)
        interact_just_pressed = input_comp.interact_pressed and not self.last_interact_pressed
        self.last_interact_pressed = input_comp.interact_pressed
        
        if nearby_door and interact_just_pressed:
            door = nearby_door.get_component(DoorComponent)
            door_pos = nearby_door.get_component(PositionComponent)
            door_size = nearby_door.get_component(SizeComponent)
            
            # Check if something is blocking the door before allowing toggle
            door_rect = (door_pos.x - door_size.width // 2, door_pos.y - door_size.height // 2,
                        door_size.width, door_size.height)
            
            # Check for players, enemies, or other obstacles blocking the door
            is_blocked = False
            
            # Check players
            for player_entity in self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent):
                player_pos = player_entity.get_component(PositionComponent)
                player_size = player_entity.get_component(SizeComponent)
                margin = player_size.hitbox_margin
                player_rect = (player_pos.x + margin, player_pos.y + margin,
                              player_size.width - margin * 2, player_size.height - margin * 2)
                if check_collision(door_rect, player_rect):
                    is_blocked = True
                    break
            
            # Check enemies
            if not is_blocked:
                for enemy_entity in self.world.get_entities_with(EnemyComponent, PositionComponent, SizeComponent):
                    enemy_pos = enemy_entity.get_component(PositionComponent)
                    enemy_size = enemy_entity.get_component(SizeComponent)
                    enemy_rect = (enemy_pos.x, enemy_pos.y, enemy_size.width, enemy_size.height)
                    if check_collision(door_rect, enemy_rect):
                        is_blocked = True
                        break
            
            # Check other obstacles (rocks, walls, etc.)
            if not is_blocked:
                for obstacle_entity in self.world.get_entities_with(PositionComponent, SizeComponent, CollisionComponent):
                    if obstacle_entity.id == nearby_door.id:
                        continue  # Skip the door itself
                    obs_coll = obstacle_entity.get_component(CollisionComponent)
                    if obs_coll.layer != "obstacle":
                        continue
                    obs_pos = obstacle_entity.get_component(PositionComponent)
                    obs_size = obstacle_entity.get_component(SizeComponent)
                    obs_rect = get_entity_rect(obstacle_entity)
                    if obs_rect and check_collision(door_rect, obs_rect):
                        is_blocked = True
                        break
            
            # Only toggle if not blocked
            if not is_blocked:
                door.is_open = not door.is_open
                
                # Update door visual
                sprite_comp = nearby_door.get_component(SpriteComponent)
                if sprite_comp and sprite_comp.door_panel:
                    if door.is_open:
                        sprite_comp.door_panel.color = (100, 100, 100)  # Gray when open
                        sprite_comp.door_panel.opacity = 100
                    else:
                        sprite_comp.door_panel.color = (139, 90, 43)  # Brown when closed
                        sprite_comp.door_panel.opacity = 255
        
        # Update tooltip
        if self.game_window and hasattr(self.game_window, 'door_tooltip'):
            if nearby_door:
                door = nearby_door.get_component(DoorComponent)
                door_pos = nearby_door.get_component(PositionComponent)
                door_size = nearby_door.get_component(SizeComponent)
                
                if door.is_open:
                    self.game_window.door_tooltip.text = "Press SPACE to close"
                else:
                    self.game_window.door_tooltip.text = "Press SPACE to open"
                
                # Position tooltip near door
                if self.game_window.world and self.game_window.world.camera:
                    camera = self.game_window.world.camera
                    screen_x, screen_y = camera.world_to_screen(door_pos.x, door_pos.y)
                    self.game_window.door_tooltip.x = screen_x
                    self.game_window.door_tooltip.y = screen_y + door_size.height // 2 + 20
                
                self.game_window.door_tooltip.visible = True
            else:
                self.game_window.door_tooltip.visible = False


class StairsSystem(System):
    """Handles stairs movement (changing height levels)."""
    priority = 23
    
    def update(self, dt: float):
        # Check players on stairs
        for player_entity in self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent, HeightComponent):
            player_pos = player_entity.get_component(PositionComponent)
            player_size = player_entity.get_component(SizeComponent)
            player_height = player_entity.get_component(HeightComponent)
            
            player_center_x = player_pos.x + player_size.width / 2
            player_center_y = player_pos.y + player_size.height / 2
            player_rect = (player_pos.x, player_pos.y, player_size.width, player_size.height)
            
            # Check if player is on stairs
            for stairs_entity in self.world.get_entities_with(StairsComponent, PositionComponent, SizeComponent, HeightComponent):
                stairs_pos = stairs_entity.get_component(PositionComponent)
                stairs_size = stairs_entity.get_component(SizeComponent)
                stairs_comp = stairs_entity.get_component(StairsComponent)
                stairs_height = stairs_entity.get_component(HeightComponent)
                
                stairs_rect = (stairs_pos.x - stairs_size.width // 2, stairs_pos.y - stairs_size.height // 2,
                              stairs_size.width, stairs_size.height)
                
                if check_collision(player_rect, stairs_rect):
                    # Check if moving in stairs direction
                    dx = stairs_comp.direction_x
                    dy = stairs_comp.direction_y
                    if dx == 0 and dy == 0:
                        continue
                    
                    # Determine if going up or down based on player position relative to stairs
                    player_to_stairs_dx = player_center_x - stairs_pos.x
                    player_to_stairs_dy = player_center_y - stairs_pos.y
                    dot_product = player_to_stairs_dx * dx + player_to_stairs_dy * dy
                    
                    if dot_product > 0:  # Moving in direction of stairs (going up)
                        if player_height.level == stairs_comp.from_level:
                            player_height.level = stairs_comp.to_level
                    else:  # Moving opposite direction (going down)
                        if player_height.level == stairs_comp.to_level:
                            player_height.level = stairs_comp.from_level
        
        # Check enemies on stairs
        for enemy_entity in self.world.get_entities_with(EnemyComponent, PositionComponent, SizeComponent, HeightComponent):
            enemy_pos = enemy_entity.get_component(PositionComponent)
            enemy_size = enemy_entity.get_component(SizeComponent)
            enemy_height = enemy_entity.get_component(HeightComponent)
            
            enemy_rect = (enemy_pos.x, enemy_pos.y, enemy_size.width, enemy_size.height)
            
            # Check if enemy is on stairs
            for stairs_entity in self.world.get_entities_with(StairsComponent, PositionComponent, SizeComponent, HeightComponent):
                stairs_pos = stairs_entity.get_component(PositionComponent)
                stairs_size = stairs_entity.get_component(SizeComponent)
                stairs_comp = stairs_entity.get_component(StairsComponent)
                
                stairs_rect = (stairs_pos.x - stairs_size.width // 2, stairs_pos.y - stairs_size.height // 2,
                              stairs_size.width, stairs_size.height)
                
                if check_collision(enemy_rect, stairs_rect):
                    # Enemies automatically move up/down stairs based on direction
                    if enemy_height.level == stairs_comp.from_level:
                        enemy_height.level = stairs_comp.to_level
                    elif enemy_height.level == stairs_comp.to_level:
                        enemy_height.level = stairs_comp.from_level


class HarvestSystem(System):
    """Handles tree harvesting."""
    priority = 25
    
    def update(self, dt: float):
        # Get player
        player_entity = None
        for entity in self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent, InputComponent):
            player_entity = entity
            break
        
        if not player_entity:
            return
        
        player_pos = player_entity.get_component(PositionComponent)
        player_size = player_entity.get_component(SizeComponent)
        player_comp = player_entity.get_component(PlayerComponent)
        input_comp = player_entity.get_component(InputComponent)
        
        player_center_x = player_pos.x + player_size.width / 2
        player_center_y = player_pos.y + player_size.height / 2
        
        # Find nearby tree
        nearby_tree_id = None
        min_dist = float('inf')
        
        if input_comp.harvest_pressed:
            for entity in self.world.get_entities_with(TreeComponent, PositionComponent, SizeComponent):
                tree = entity.get_component(TreeComponent)
                if tree.is_chopped:
                    continue
                
                tree_pos = entity.get_component(PositionComponent)
                # Tree position is stored as center
                tree_center_x = tree_pos.x
                tree_center_y = tree_pos.y
                
                dx = player_center_x - tree_center_x
                dy = player_center_y - tree_center_y
                distance = math.sqrt(dx**2 + dy**2)
                
                if distance <= HARVEST_RANGE and distance < min_dist:
                    min_dist = distance
                    nearby_tree_id = entity.id
        
        # Update all trees
        for entity in self.world.get_entities_with(TreeComponent, PositionComponent, SizeComponent):
            tree = entity.get_component(TreeComponent)
            
            # Skip already chopped trees
            if tree.is_chopped:
                continue
            
            if entity.id == nearby_tree_id and input_comp.harvest_pressed:
                tree.current_chopper = player_entity.id
                tree.chop_progress += dt / TREE_CHOP_TIME
                
                if tree.chop_progress >= 1.0:
                    tree.is_chopped = True
                    player_comp.wood += 1
                    # Hide sprites
                    sprite = entity.get_component(SpriteComponent)
                    if sprite:
                        sprite.cleanup()
                    self.world.remove_entity(entity.id)
        else:
                # Only reset if this tree was being chopped by this player
                if tree.current_chopper == player_entity.id:
                    tree.current_chopper = None
                    tree.chop_progress = 0.0


class WallSystem(System):
    """Handles wall state updates."""
    priority = 26
    
    def update(self, dt: float):
        # Get player
        player_entity = None
        for entity in self.world.get_entities_with(PlayerComponent, PositionComponent, SizeComponent):
            player_entity = entity
            break
                
        if not player_entity:
            return
        
        player_pos = player_entity.get_component(PositionComponent)
        player_size = player_entity.get_component(SizeComponent)
        player_rect = (player_pos.x, player_pos.y, player_size.width, player_size.height)
        
        # Handle walls
        for entity in self.world.get_entities_with(WallComponent, PositionComponent, SizeComponent):
            wall = entity.get_component(WallComponent)
            if not wall.is_solid and wall.owner_id == player_entity.id:
                wall_pos = entity.get_component(PositionComponent)
                wall_size = entity.get_component(SizeComponent)
                wall_rect = (wall_pos.x - wall_size.width // 2, wall_pos.y - wall_size.height // 2,
                           wall_size.width, wall_size.height)
                
                if not check_collision(player_rect, wall_rect):
                    wall.is_solid = True
        
        # Handle doors - make them blocking when closed and player moves away
        for entity in self.world.get_entities_with(DoorComponent, PositionComponent, SizeComponent):
            door = entity.get_component(DoorComponent)
            if not door.is_blocking and door.owner_id == player_entity.id and not door.is_open:
                door_pos = entity.get_component(PositionComponent)
                door_size = entity.get_component(SizeComponent)
                door_rect = (door_pos.x - door_size.width // 2, door_pos.y - door_size.height // 2,
                           door_size.width, door_size.height)
                
                if not check_collision(player_rect, door_rect):
                    door.is_blocking = True


class RenderSystem(System):
    """Updates sprite positions based on camera."""
    priority = 100
    
    def update(self, dt: float):
        camera = self.world.camera
        if not camera:
            return
        
        for entity in self.world.get_entities_with(PositionComponent, SpriteComponent):
            pos = entity.get_component(PositionComponent)
            sprite_comp = entity.get_component(SpriteComponent)
            size = entity.get_component(SizeComponent)
            tree = entity.get_component(TreeComponent)
            rock = entity.get_component(RockComponent)
            wall = entity.get_component(WallComponent)
            enemy = entity.get_component(EnemyComponent)
            proj = entity.get_component(ProjectileComponent)
            
            if not sprite_comp.visible:
                continue
            
            screen_x, screen_y = camera.world_to_screen(pos.x, pos.y)
            
            # Handle player/enemy sprites
            if sprite_comp.sprite:
                offset_x = 0
                offset_y = 0
                if (tree or wall) and size:
                    offset_x = -size.width / 2
                    offset_y = -size.height / 2
                sprite_comp.sprite.x = screen_x
                sprite_comp.sprite.y = screen_y
                if offset_x or offset_y:
                    sprite_comp.sprite.x += offset_x
                    sprite_comp.sprite.y += offset_y
            
            # Handle shape-based entities
            if tree and not tree.is_chopped:
                size_comp = entity.get_component(SizeComponent)
                # Tree position is center, convert to top-left for rendering
                tree_top_left_x = screen_x - size_comp.width / 2
                tree_top_left_y = screen_y - size_comp.height / 2
                
                if len(sprite_comp.shapes) >= 2:
                    # Trunk (centered horizontally, at bottom)
                    sprite_comp.shapes[0].x = tree_top_left_x + size_comp.width / 2 - size_comp.width // 6
                    sprite_comp.shapes[0].y = tree_top_left_y
                    # Leaves (centered horizontally, above trunk)
                    sprite_comp.shapes[1].x = tree_top_left_x + size_comp.width / 2
                    sprite_comp.shapes[1].y = tree_top_left_y + size_comp.height + size_comp.height // 3
                
                # Update progress bar
                if sprite_comp.progress_bar_bg and sprite_comp.progress_bar_fg:
                    bar_width = size_comp.width + 10
                    sprite_comp.progress_bar_bg.x = tree_top_left_x + size_comp.width / 2 - bar_width // 2
                    sprite_comp.progress_bar_bg.y = tree_top_left_y + size_comp.height + 10
                    sprite_comp.progress_bar_fg.x = sprite_comp.progress_bar_bg.x
                    sprite_comp.progress_bar_fg.y = sprite_comp.progress_bar_bg.y
                    
                    if tree.current_chopper and tree.chop_progress > 0:
                        sprite_comp.progress_bar_bg.visible = True
                        sprite_comp.progress_bar_fg.visible = True
                        sprite_comp.progress_bar_fg.width = bar_width * tree.chop_progress
                else:
                    sprite_comp.progress_bar_bg.visible = False
                    sprite_comp.progress_bar_fg.visible = False
                continue
            
            if rock:
                for shape in sprite_comp.shapes:
                    shape.x = screen_x
                    shape.y = screen_y
                continue
            
            if wall:
                size_comp = entity.get_component(SizeComponent)
                half_w = size_comp.width // 2
                half_h = size_comp.height // 2
                actual_x = screen_x - half_w
                actual_y = screen_y - half_h
                
                if len(sprite_comp.shapes) >= 5:
                    sprite_comp.shapes[0].x = actual_x  # Main
                    sprite_comp.shapes[0].y = actual_y
                    sprite_comp.shapes[1].x = actual_x  # Border
                    sprite_comp.shapes[1].y = actual_y
                    sprite_comp.shapes[2].x = actual_x + 2  # Grain1
                    sprite_comp.shapes[2].y = actual_y + size_comp.height // 4
                    sprite_comp.shapes[3].x = actual_x + 2  # Grain2
                    sprite_comp.shapes[3].y = actual_y + size_comp.height // 2
                    sprite_comp.shapes[4].x = actual_x + 2  # Grain3
                    sprite_comp.shapes[4].y = actual_y + 3 * size_comp.height // 4
                continue
            
            door = entity.get_component(DoorComponent)
            if door:
                size_comp = entity.get_component(SizeComponent)
                half_w = size_comp.width // 2
                half_h = size_comp.height // 2
                actual_x = screen_x - half_w
                actual_y = screen_y - half_h
                
                if len(sprite_comp.shapes) >= 2:
                    sprite_comp.shapes[0].x = actual_x  # Frame
                    sprite_comp.shapes[0].y = actual_y
                    if sprite_comp.door_panel:
                        sprite_comp.door_panel.x = actual_x + 2
                        sprite_comp.door_panel.y = actual_y + 2
                continue
            
            stairs = entity.get_component(StairsComponent)
            if stairs:
                size_comp = entity.get_component(SizeComponent)
                half_w = size_comp.width // 2
                half_h = size_comp.height // 2
                actual_x = screen_x - half_w
                actual_y = screen_y - half_h
                
                for i, shape in enumerate(sprite_comp.shapes):
                    if i == 0:
                        shape.x = actual_x  # Base
                        shape.y = actual_y
                    else:
                        step_y = actual_y + (size_comp.height // 3) * (i - 1)
                        shape.x = actual_x
                        shape.y = step_y
                continue
            
            if enemy and sprite_comp.shapes and not sprite_comp.sprite:
                for shape in sprite_comp.shapes:
                    shape.x = screen_x
                    shape.y = screen_y
                continue
            
            if proj and sprite_comp.shapes and not sprite_comp.sprite:
                center_x = screen_x + (size.width if size else PROJECTILE_SIZE) / 2
                center_y = screen_y + (size.height if size else PROJECTILE_SIZE) / 2
                for shape in sprite_comp.shapes:
                    shape.x = center_x
                    shape.y = center_y
                continue

# ============================================================================
# ENTITY FACTORIES
# ============================================================================

def create_player(world: World, x: float, y: float, player_id: int = 1, color=GREEN) -> Entity:
    """Create a player entity with all required components."""
    entity = world.create_entity()
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(VelocityComponent(speed=PLAYER_SPEED))
    entity.add_component(SizeComponent(width=PLAYER_SIZE, height=PLAYER_SIZE, hitbox_margin=PLAYER_HITBOX_MARGIN))
    entity.add_component(PlayerComponent(player_id=player_id))
    entity.add_component(InputComponent())
    entity.add_component(HeightComponent(level=0))  # Players start at ground level
    entity.add_component(CollisionComponent(layer="player", collides_with=["enemy", "obstacle"]))
    entity.add_component(TagComponent(tags={"player"}))
    
    # Create sprite
    sprite_comp = SpriteComponent()
    format_str = 'RGBA'
    pitch = PLAYER_SIZE * len(format_str)
    data = bytes(color + (255,)) * (PLAYER_SIZE * PLAYER_SIZE)
    image = pyglet.image.ImageData(PLAYER_SIZE, PLAYER_SIZE, format_str, data, pitch=-pitch)
    sprite_comp.sprite = pyglet.sprite.Sprite(image, x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2, batch=world.batch)
    entity.add_component(sprite_comp)
    
    return entity

def create_enemy(world: World, x: float, y: float, enemy_id: int = None) -> Entity:
    """Create an enemy entity."""
    entity = world.create_entity()
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(VelocityComponent(speed=ENEMY_SPEED))
    entity.add_component(SizeComponent(width=ENEMY_SIZE, height=ENEMY_SIZE))
    entity.add_component(EnemyComponent(enemy_id=enemy_id or random.randint(1000, 9999)))
    entity.add_component(HeightComponent(level=0))  # Enemies start at ground level
    entity.add_component(CollisionComponent(layer="enemy", collides_with=["player", "projectile"]))
    entity.add_component(TagComponent(tags={"enemy"}))
    
    sprite_comp = SpriteComponent()
    if world.render_resources:
        image = world.render_resources.get_enemy_image()
        sprite_comp.sprite = pyglet.sprite.Sprite(image, batch=world.batch)
    if not sprite_comp.sprite:
        sprite_comp.add_shape(shapes.Rectangle(0, 0, ENEMY_SIZE, ENEMY_SIZE, color=RED, batch=world.batch))
        border = shapes.Rectangle(0, 0, ENEMY_SIZE, ENEMY_SIZE, color=WHITE, batch=world.batch)
        border.opacity = 128
        sprite_comp.add_shape(border)
    entity.add_component(sprite_comp)
    
    return entity

def create_projectile(world: World, x: float, y: float, direction_x: float, direction_y: float, 
                     owner_id: int = 1, player_velocity_x: float = 0, player_velocity_y: float = 0) -> Entity:
    """Create a projectile entity."""
    entity = world.create_entity()
    
    # Normalize direction
    length = math.sqrt(direction_x**2 + direction_y**2)
    if length > 0:
        base_dx = (direction_x / length) * PROJECTILE_SPEED
        base_dy = (direction_y / length) * PROJECTILE_SPEED
    else:
        base_dx = 0
        base_dy = PROJECTILE_SPEED
    
    # Add player velocity
    velocity_per_frame_x = player_velocity_x / 60.0
    velocity_per_frame_y = player_velocity_y / 60.0
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(VelocityComponent(dx=base_dx + velocity_per_frame_x, dy=base_dy + velocity_per_frame_y, speed=PROJECTILE_SPEED))
    entity.add_component(SizeComponent(width=PROJECTILE_SIZE, height=PROJECTILE_SIZE))
    entity.add_component(ProjectileComponent(owner_id=owner_id))
    entity.add_component(CollisionComponent(layer="projectile", collides_with=["enemy", "obstacle"]))
    entity.add_component(TagComponent(tags={"projectile"}))
    
    sprite_comp = SpriteComponent()
    if world.render_resources:
        image = world.render_resources.get_projectile_image()
        sprite_comp.sprite = pyglet.sprite.Sprite(image, batch=world.batch)
    if not sprite_comp.sprite:
        sprite_comp.add_shape(shapes.Circle(0, 0, PROJECTILE_SIZE // 2, color=YELLOW, batch=world.batch))
    entity.add_component(sprite_comp)
    
    return entity

def create_rock(world: World, x: float, y: float, size: int) -> Entity:
    """Create a rock entity."""
    entity = world.create_entity()
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(SizeComponent(width=size, height=size))
    entity.add_component(RockComponent(rock_id=random.randint(3000, 9999)))
    entity.add_component(HeightComponent(level=1))  # Rocks have height 1
    entity.add_component(CollisionComponent(layer="obstacle", collides_with=["player", "enemy", "projectile"]))
    entity.add_component(TagComponent(tags={"rock", "obstacle"}))
    
    sprite_comp = SpriteComponent()
    sprite_comp.add_shape(shapes.Rectangle(0, 0, size, size, color=(100, 100, 100), batch=world.batch))
    border = shapes.Rectangle(0, 0, size, size, color=(150, 150, 150), batch=world.batch)
    border.opacity = 200
    sprite_comp.add_shape(border)
    entity.add_component(sprite_comp)
    
    return entity

def create_tree(world: World, x: float, y: float, tree_id: int = None) -> Entity:
    """Create a tree entity. x, y are center coordinates."""
    entity = world.create_entity()
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(SizeComponent(width=TREE_SIZE, height=TREE_SIZE))
    entity.add_component(TreeComponent(tree_id=tree_id or random.randint(2000, 9999)))
    entity.add_component(CollisionComponent(layer="obstacle", collides_with=["player", "enemy", "projectile"]))
    entity.add_component(TagComponent(tags={"tree", "obstacle"}))
    
    sprite_comp = SpriteComponent()
    # Trunk
    sprite_comp.add_shape(shapes.Rectangle(0, 0, TREE_SIZE // 3, TREE_SIZE, color=(139, 69, 19), batch=world.batch))
    # Leaves
    sprite_comp.add_shape(shapes.Circle(0, 0, TREE_SIZE // 2, color=(34, 139, 34), batch=world.batch))
    # Progress bar
    bar_width = TREE_SIZE + 10
    sprite_comp.progress_bar_bg = shapes.Rectangle(0, 0, bar_width, 4, color=(50, 50, 50), batch=world.batch)
    sprite_comp.progress_bar_fg = shapes.Rectangle(0, 0, 0, 4, color=(0, 255, 0), batch=world.batch)
    sprite_comp.progress_bar_bg.visible = False
    sprite_comp.progress_bar_fg.visible = False
    entity.add_component(sprite_comp)
    
    return entity

def create_wall(world: World, x: float, y: float, owner_id: int = None) -> Entity:
    """Create a wall entity."""
    entity = world.create_entity()
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(SizeComponent(width=WALL_SIZE, height=WALL_SIZE))
    entity.add_component(WallComponent(owner_id=owner_id, is_solid=False))
    entity.add_component(HeightComponent(level=1))  # Walls have height 1
    entity.add_component(CollisionComponent(layer="obstacle", collides_with=["player", "enemy", "projectile"]))
    entity.add_component(TagComponent(tags={"wall", "obstacle"}))
    
    sprite_comp = SpriteComponent()
    if world.render_resources:
        image = world.render_resources.get_wall_image()
        sprite_comp.sprite = pyglet.sprite.Sprite(image, batch=world.batch)
    else:
        sprite_comp.add_shape(shapes.Rectangle(0, 0, WALL_SIZE, WALL_SIZE, color=(139, 90, 43), batch=world.batch))
        border = shapes.Rectangle(0, 0, WALL_SIZE, WALL_SIZE, color=(101, 67, 33), batch=world.batch)
        border.opacity = 200
        sprite_comp.add_shape(border)
        sprite_comp.add_shape(shapes.Rectangle(0, 0, WALL_SIZE - 4, 2, color=(120, 75, 35), batch=world.batch))
        sprite_comp.add_shape(shapes.Rectangle(0, 0, WALL_SIZE - 4, 2, color=(120, 75, 35), batch=world.batch))
        sprite_comp.add_shape(shapes.Rectangle(0, 0, WALL_SIZE - 4, 2, color=(120, 75, 35), batch=world.batch))
    entity.add_component(sprite_comp)
    
    return entity

def create_door(world: World, x: float, y: float, owner_id: int = None) -> Entity:
    """Create a door entity."""
    entity = world.create_entity()
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(SizeComponent(width=WALL_SIZE, height=WALL_SIZE))
    entity.add_component(DoorComponent(owner_id=owner_id, is_open=False, is_blocking=False))
    entity.add_component(HeightComponent(level=1))  # Doors have height 1 like walls
    entity.add_component(CollisionComponent(layer="obstacle", collides_with=["player", "enemy", "projectile"]))
    entity.add_component(TagComponent(tags={"door", "obstacle"}))
    
    sprite_comp = SpriteComponent()
    # Door frame (always visible)
    sprite_comp.add_shape(shapes.Rectangle(0, 0, WALL_SIZE, WALL_SIZE, color=(101, 67, 33), batch=world.batch))
    # Door panel (changes color when open)
    sprite_comp.door_panel = shapes.Rectangle(0, 0, WALL_SIZE - 4, WALL_SIZE - 4, color=(139, 90, 43), batch=world.batch)
    sprite_comp.add_shape(sprite_comp.door_panel)
    entity.add_component(sprite_comp)
    
    return entity

def create_stairs(world: World, x: float, y: float, direction_x: float, direction_y: float, from_level: int, to_level: int, owner_id: int = None) -> Entity:
    """Create a stairs entity."""
    entity = world.create_entity()
    
    entity.add_component(PositionComponent(x=x, y=y))
    entity.add_component(SizeComponent(width=WALL_SIZE, height=WALL_SIZE))
    entity.add_component(StairsComponent(owner_id=owner_id, direction_x=direction_x, direction_y=direction_y, from_level=from_level, to_level=to_level))
    entity.add_component(HeightComponent(level=from_level))  # Stairs are at the from_level
    # Stairs don't block movement - they're just for changing height levels
    # No CollisionComponent - stairs allow passage
    entity.add_component(TagComponent(tags={"stairs"}))
    
    sprite_comp = SpriteComponent()
    # Stairs base
    sprite_comp.add_shape(shapes.Rectangle(0, 0, WALL_SIZE, WALL_SIZE, color=(120, 120, 120), batch=world.batch))
    # Stairs steps
    for i in range(3):
        step_y = (WALL_SIZE // 3) * i
        sprite_comp.add_shape(shapes.Rectangle(0, step_y, WALL_SIZE, WALL_SIZE // 6, color=(150, 150, 150), batch=world.batch))
    entity.add_component(sprite_comp)
    
    return entity

def generate_rocks_ecs(world: World, num_rocks: int, exclude_x=None, exclude_y=None, exclude_radius=300):
    """Generate rocks using ECS."""
    rocks = []
    attempts = 0
    max_attempts = num_rocks * 30
    
    num_clusters = max(3, num_rocks // 8)
    cluster_centers = []
    
    for _ in range(num_clusters):
        cluster_x = random.randint(GRID_SIZE * 5, WORLD_WIDTH - GRID_SIZE * 5)
        cluster_y = random.randint(GRID_SIZE * 5, WORLD_HEIGHT - GRID_SIZE * 5)
        cluster_x, cluster_y = snap_to_grid(cluster_x, cluster_y)
        cluster_centers.append((cluster_x, cluster_y))
    
    rocks_per_cluster = num_rocks // num_clusters
    remaining_rocks = num_rocks
    
    for cluster_x, cluster_y in cluster_centers:
        cluster_rocks = 0
        cluster_max = rocks_per_cluster if remaining_rocks > rocks_per_cluster else remaining_rocks
        cluster_radius = GRID_SIZE * 8
        
        while cluster_rocks < cluster_max and attempts < max_attempts:
            attempts += 1
            
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(0, cluster_radius)
            x = cluster_x + math.cos(angle) * distance
            y = cluster_y + math.sin(angle) * distance
            x, y = snap_to_grid(x, y)
            
            size = GRID_SIZE
            
            if x < size or x > WORLD_WIDTH - size or y < size or y > WORLD_HEIGHT - size:
                continue
            
            if exclude_x and exclude_y:
                dist = math.sqrt((x - exclude_x)**2 + (y - exclude_y)**2)
                if dist < exclude_radius:
                    continue
            
            new_rect = (x - size // 2, y - size // 2, size, size)
            overlap = False
            for existing in rocks:
                pos = existing.get_component(PositionComponent)
                sz = existing.get_component(SizeComponent)
                if check_collision(new_rect, (pos.x, pos.y, sz.width, sz.height)):
                    overlap = True
                    break
            
            if not overlap:
                entity = create_rock(world, x - size // 2, y - size // 2, size)
                rocks.append(entity)
                cluster_rocks += 1
                remaining_rocks -= 1
        
        if remaining_rocks <= 0:
            break
    
    return rocks

def generate_trees_ecs(world: World, num_trees: int, exclude_x=None, exclude_y=None, exclude_radius=300, existing_rocks=None):
    """Generate trees using ECS."""
    trees = []
    attempts = 0
    max_attempts = num_trees * 20
    existing_rocks = existing_rocks or []
    
    while len(trees) < num_trees and attempts < max_attempts:
        attempts += 1
        x = random.randint(TREE_SIZE, WORLD_WIDTH - TREE_SIZE)
        y = random.randint(TREE_SIZE, WORLD_HEIGHT - TREE_SIZE)
        
        if exclude_x and exclude_y:
            dist = math.sqrt((x - exclude_x)**2 + (y - exclude_y)**2)
            if dist < exclude_radius:
                continue
        
        # x, y are center coordinates, create rect for overlap checking
        new_rect = (x - TREE_SIZE // 2, y - TREE_SIZE // 2, TREE_SIZE, TREE_SIZE)
        overlap = False
        
        for existing in trees:
            existing_rect = get_entity_rect(existing)
            if existing_rect and check_collision(new_rect, existing_rect):
                overlap = True
                break
        
        if not overlap:
            for rock in existing_rocks:
                rock_rect = get_entity_rect(rock)
                if rock_rect and check_collision(new_rect, rock_rect):
                    overlap = True
                    break
        
        if not overlap:
            entity = create_tree(world, x, y)
            trees.append(entity)
    
    return trees

def spawn_enemy_ecs(world: World, player_x=None, player_y=None, obstacles=None):
    """Spawn an enemy at a valid location."""
    obstacles = obstacles or []
    max_attempts = 50
    
    for _ in range(max_attempts):
        if player_x is not None and player_y is not None:
            spawn_distance = max(SCREEN_WIDTH, SCREEN_HEIGHT) + 100
            angle = random.uniform(0, 2 * math.pi)
            spawn_x = player_x + math.cos(angle) * spawn_distance
            spawn_y = player_y + math.sin(angle) * spawn_distance
            spawn_x = max(ENEMY_SIZE, min(WORLD_WIDTH - ENEMY_SIZE, spawn_x))
            spawn_y = max(ENEMY_SIZE, min(WORLD_HEIGHT - ENEMY_SIZE, spawn_y))
        else:
            side = random.randint(0, 3)
            if side == 0:
                spawn_x = random.randint(0, WORLD_WIDTH)
                spawn_y = WORLD_HEIGHT
            elif side == 1:
                spawn_x = WORLD_WIDTH
                spawn_y = random.randint(0, WORLD_HEIGHT)
            elif side == 2:
                spawn_x = random.randint(0, WORLD_WIDTH)
                spawn_y = -ENEMY_SIZE
            else:
                spawn_x = -ENEMY_SIZE
                spawn_y = random.randint(0, WORLD_HEIGHT)
        
        spawn_rect = (spawn_x, spawn_y, ENEMY_SIZE, ENEMY_SIZE)
        valid = True
        
        for obs in obstacles:
            tree = obs.get_component(TreeComponent)
            if tree and tree.is_chopped:
                continue
            pos = obs.get_component(PositionComponent)
            sz = obs.get_component(SizeComponent)
            if check_collision(spawn_rect, (pos.x, pos.y, sz.width, sz.height)):
                valid = False
                break
        
        if valid:
            return create_enemy(world, spawn_x, spawn_y)
    
    # Fallback spawn
    side = random.randint(0, 3)
    if side == 0:
        return create_enemy(world, random.randint(0, WORLD_WIDTH), WORLD_HEIGHT)
    elif side == 1:
        return create_enemy(world, WORLD_WIDTH, random.randint(0, WORLD_HEIGHT))
    elif side == 2:
        return create_enemy(world, random.randint(0, WORLD_WIDTH), -ENEMY_SIZE)
    else:
        return create_enemy(world, -ENEMY_SIZE, random.randint(0, WORLD_HEIGHT))

# ============================================================================
# NETWORK MANAGER
# ============================================================================

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
        self.send_interval = 1.0 / 20
        self.received_messages = []
        self.receive_lock = threading.Lock()
        self.pending_data = b''
        
    def start_host(self):
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
        except socket.error:
            self.connected = False
        except Exception:
            self.connected = False
        return False
    
    def start_receive_thread(self):
        if not self.receive_thread or not self.receive_thread.is_alive():
            self.receive_thread = threading.Thread(target=self._receive_thread, daemon=True)
            self.receive_thread.start()
    
    def receive_data_non_blocking(self):
        messages = []
        with self.receive_lock:
            if self.received_messages:
                messages = self.received_messages[:]
                self.received_messages.clear()
        return messages
    
    def _receive_thread(self):
        while self.running and self.connected:
            try:
                socket_to_use = self.client_socket if self.is_host else self.socket
                if not socket_to_use:
                    time.sleep(0.01)
                    continue
                
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
        self.running = False
        self.connected = False
        if self.client_socket:
            self.client_socket.close()
        if self.socket:
            self.socket.close()

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# ============================================================================
# MENU AND GAME OVER WINDOWS
# ============================================================================

class GameOverWindow(pyglet.window.Window):
    def __init__(self, day_count, is_multiplayer=False, is_host=False, host_ip='127.0.0.1'):
        super().__init__(width=SCREEN_WIDTH, height=SCREEN_HEIGHT, caption="Game Over")
        self.batch = pyglet.graphics.Batch()
        self.is_multiplayer = is_multiplayer
        self.is_host = is_host
        self.host_ip = host_ip
        
        self.title_label = pyglet.text.Label(
            'GAME OVER',
            font_name='Arial', font_size=48,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 150,
            anchor_x='center', anchor_y='center',
            color=(255, 50, 50, 255), batch=self.batch
        )
        
        self.day_label = pyglet.text.Label(
            f'You survived {day_count} day{"s" if day_count != 1 else ""}',
            font_name='Arial', font_size=24,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 + 50,
            anchor_x='center', anchor_y='center',
            color=WHITE, batch=self.batch
        )
        
        self.retry_label = pyglet.text.Label(
            '1. Try Again',
            font_name='Arial', font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 - 30,
            anchor_x='center', anchor_y='center',
            color=GREEN, batch=self.batch
        )
        
        self.menu_label = pyglet.text.Label(
            '2. Return to Main Menu',
            font_name='Arial', font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 - 80,
            anchor_x='center', anchor_y='center',
            color=CYAN, batch=self.batch
        )
        
        self.instructions_label = pyglet.text.Label(
            'Press 1 or 2 to select',
            font_name='Arial', font_size=16,
            x=SCREEN_WIDTH // 2, y=100,
            anchor_x='center', anchor_y='center',
            color=WHITE, batch=self.batch
        )
    
    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.NUM_1 or symbol == pyglet.window.key._1:
            self.retry_game()
        elif symbol == pyglet.window.key.NUM_2 or symbol == pyglet.window.key._2:
            self.return_to_menu()
    
    def retry_game(self):
        window = GameWindow(is_multiplayer=self.is_multiplayer, is_host=self.is_host, host_ip=self.host_ip)
        ScreenManager.set_window(window)
    
    def return_to_menu(self):
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
        
        self.title_label = pyglet.text.Label(
            'CUBE SHOOTER',
            font_name='Arial', font_size=48,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 150,
            anchor_x='center', anchor_y='center',
            color=WHITE, batch=self.batch
        )
        
        self.single_player_label = pyglet.text.Label(
            '1. Single Player',
            font_name='Arial', font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 + 50,
            anchor_x='center', anchor_y='center',
            color=GREEN, batch=self.batch
        )
        
        self.multiplayer_label = pyglet.text.Label(
            '2. Multiplayer (Host)',
            font_name='Arial', font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2,
            anchor_x='center', anchor_y='center',
            color=CYAN, batch=self.batch
        )
        
        self.join_label = pyglet.text.Label(
            '3. Join Game',
            font_name='Arial', font_size=32,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 - 50,
            anchor_x='center', anchor_y='center',
            color=BLUE, batch=self.batch
        )
        
        self.instructions_label = pyglet.text.Label(
            'Press 1, 2, or 3 to select',
            font_name='Arial', font_size=16,
            x=SCREEN_WIDTH // 2, y=100,
            anchor_x='center', anchor_y='center',
            color=WHITE, batch=self.batch
        )
    
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
        print("="*50 + "\n")
        
        window = GameWindow(is_multiplayer=True, is_host=True)
        ScreenManager.set_window(window)
    
    def start_join(self):
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

# ============================================================================
# GAME WINDOW (ECS-based)
# ============================================================================

class GameWindow(pyglet.window.Window):
    def __init__(self, is_multiplayer=False, is_host=False, host_ip='127.0.0.1'):
        super().__init__(width=SCREEN_WIDTH, height=SCREEN_HEIGHT, caption="Cube Shooter Game")
        self.batch = pyglet.graphics.Batch()
        self.is_multiplayer = is_multiplayer
        self.is_host = is_host
        self.game_active = True
        self.host_ip = host_ip
        self.my_player_id = 1 if is_host else 2
        
        # Initialize ECS World
        self.world = World()
        self.world.batch = self.batch
        self.world.camera = Camera()
        self.world.spatial = SpatialPartition(WORLD_WIDTH, WORLD_HEIGHT)
        self.world.render_resources = RenderResourceManager()
        
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
        
        # Create player entity
        if is_multiplayer:
            if is_host:
                self.player_entity = create_player(self.world, WORLD_WIDTH // 4, WORLD_HEIGHT // 2, 1, GREEN)
                self.other_player_entity = create_player(self.world, 3 * WORLD_WIDTH // 4, WORLD_HEIGHT // 2, 2, CYAN)
            else:
                self.player_entity = create_player(self.world, 3 * WORLD_WIDTH // 4, WORLD_HEIGHT // 2, 2, CYAN)
                self.other_player_entity = create_player(self.world, WORLD_WIDTH // 4, WORLD_HEIGHT // 2, 1, GREEN)
        else:
            self.player_entity = create_player(self.world, WORLD_WIDTH // 2, WORLD_HEIGHT // 2, 1, GREEN)
            self.other_player_entity = None
        
        # Get player starting position for obstacle exclusion
        player_pos = self.player_entity.get_component(PositionComponent)
        player_start_x = player_pos.x
        player_start_y = player_pos.y
        
        # Generate environment
        self.rocks = generate_rocks_ecs(self.world, MAX_ROCKS, player_start_x, player_start_y, 250)
        self.trees = generate_trees_ecs(self.world, MAX_TREES, player_start_x, player_start_y, 250, self.rocks)
        
        # Track pressed keys
        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)
        self.arrow_keys_pressed = {
            pyglet.window.key.UP: False,
            pyglet.window.key.DOWN: False,
            pyglet.window.key.LEFT: False,
            pyglet.window.key.RIGHT: False
        }
        
        # Add ECS Systems
        self.world.add_system(InputSystem(self.keys, self.arrow_keys_pressed))
        self.world.add_system(SpatialPartitionSystem())
        self.world.add_system(MovementSystem())
        self.world.add_system(EnemyAISystem())
        self.world.add_system(ProjectileSystem())
        self.world.add_system(InteractionSystem(self))
        self.world.add_system(StairsSystem())
        self.world.add_system(HarvestSystem())
        self.world.add_system(WallSystem())
        self.world.add_system(CollisionSystem(self))
        self.world.add_system(RenderSystem())
        
        # Game state
        self.frame_count = 0
        self.game_time = 0.0
        self.last_fire_time = 0.0
        self.enemy_spawn_timer = 0.0
        
        # Day/Night cycle
        self.day_count = 1
        self.is_night = False
        self.cycle_time = 0.0
        # Cached lighting color for smooth transitions
        self.current_bg_color = [0.08, 0.08, 0.12, 1.0]  # Use list for mutable interpolation
        self.target_bg_color = [0.08, 0.08, 0.12, 1.0]
        
        # Build mode
        self.build_menu_open = False
        self.build_menu_last_used = 0.0
        self.selected_building = 1
        self.building_types = {
            1: {'name': 'Wooden Wall', 'cost': WALL_WOOD_COST, 'resource': 'wood', 'type': 'wall'},
            2: {'name': 'Door', 'cost': WALL_WOOD_COST, 'resource': 'wood', 'type': 'door'},
            3: {'name': 'Stairs', 'cost': WALL_WOOD_COST, 'resource': 'wood', 'type': 'stairs'}
        }
        
        # Create UI elements
        self._create_ui()
        
        # Schedule update
        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)
        
        # Accept client connection if hosting
        if is_multiplayer and is_host:
            pyglet.clock.schedule_once(lambda dt: self.check_connection(), 0.1)
    
    def _create_ui(self):
        """Create all UI elements."""
        # Build menu
        self.build_menu_bg = shapes.Rectangle(
            SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT - 80, 300, 75,
            color=(30, 30, 30), batch=self.batch
        )
        self.build_menu_bg.opacity = 180
        self.build_menu_bg.visible = False
        
        self.build_menu_title = pyglet.text.Label(
            'BUILD MENU (1-9 to select, F to build)',
            font_name='Arial', font_size=10,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 18,
            anchor_x='center', anchor_y='center',
            color=(255, 255, 255, 255), batch=self.batch
        )
        self.build_menu_title.visible = False
        
        self.build_menu_item1 = pyglet.text.Label(
            f'[1] Wooden Wall ({WALL_WOOD_COST} wood)',
            font_name='Arial', font_size=12,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 35,
            anchor_x='center', anchor_y='center',
            color=(255, 255, 0, 255), batch=self.batch
        )
        self.build_menu_item1.visible = False
        
        self.build_menu_item2 = pyglet.text.Label(
            f'[2] Door ({WALL_WOOD_COST} wood)',
            font_name='Arial', font_size=12,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 50,
            anchor_x='center', anchor_y='center',
            color=(255, 255, 0, 255), batch=self.batch
        )
        self.build_menu_item2.visible = False
        
        self.build_menu_item3 = pyglet.text.Label(
            f'[3] Stairs ({WALL_WOOD_COST} wood)',
            font_name='Arial', font_size=12,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 65,
            anchor_x='center', anchor_y='center',
            color=(255, 255, 0, 255), batch=self.batch
        )
        self.build_menu_item3.visible = False
        
        # Enemy counter
        self.score_label = pyglet.text.Label(
            '0', font_name='Arial', font_size=14,
            x=SCREEN_WIDTH - 10, y=SCREEN_HEIGHT - 18,
            anchor_x='right', anchor_y='center',
            color=WHITE, batch=self.batch
        )
        
        # Wood icon and counter
        log_y = SCREEN_HEIGHT - 20
        log_x = 10
        self.wood_icon = shapes.Rectangle(log_x, log_y - 12, 14, 12, color=(139, 90, 43), batch=self.batch)
        self.wood_top = shapes.Circle(log_x + 7, log_y - 1, 7, color=(139, 90, 43), batch=self.batch)
        self.wood_bottom = shapes.Circle(log_x + 7, log_y - 12, 7, color=(139, 90, 43), batch=self.batch)
        self.wood_ring1 = shapes.Circle(log_x + 7, log_y - 1, 4, color=(120, 75, 35), batch=self.batch)
        self.wood_ring2 = shapes.Circle(log_x + 7, log_y - 1, 2, color=(101, 67, 33), batch=self.batch)
        self.wood_label = pyglet.text.Label('0', font_name='Arial', font_size=16, x=30, y=log_y - 6, anchor_y='center', color=WHITE, batch=self.batch)
        
        # Coin icon and counter (moved down to avoid overlap with wood)
        coin_y = SCREEN_HEIGHT - 50  # Increased gap from 20 to 30 pixels
        self.coin_icon = shapes.Circle(16, coin_y, 8, color=(255, 215, 0), batch=self.batch)
        self.coin_highlight = shapes.Circle(16, coin_y, 5, color=(255, 235, 100), batch=self.batch)
        self.coin_label = pyglet.text.Label('0', font_name='Arial', font_size=16, x=30, y=coin_y, anchor_y='center', color=WHITE, batch=self.batch)
        
        # Day/Night cycle labels
        self.day_label = pyglet.text.Label('Day 1', font_name='Arial', font_size=18, x=10, y=30, color=(255, 200, 50, 255), batch=self.batch)
        self.time_label = pyglet.text.Label('Daytime - Gather resources!', font_name='Arial', font_size=14, x=10, y=10, color=(255, 255, 150, 255), batch=self.batch)
        
        # Night warning
        self.night_warning = pyglet.text.Label(
            'NIGHT APPROACHES!', font_name='Arial', font_size=24,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT // 2 + 50,
            anchor_x='center', anchor_y='center',
            color=(255, 50, 50, 255), batch=self.batch
        )
        self.night_warning.visible = False
        self.night_warning_timer = 0.0
        
        # Connection label for multiplayer
        if self.is_multiplayer:
            self.connection_label = pyglet.text.Label(
                'Connected' if self.network and self.network.connected else 'Connecting...',
                font_name='Arial', font_size=14,
                x=10, y=SCREEN_HEIGHT - 65,
                color=GREEN if (self.network and self.network.connected) else YELLOW,
                batch=self.batch
            )
        
        # Reload indicator
        self.reload_circle_radius = 5
        self.reload_circle_bg = shapes.Circle(0, 0, self.reload_circle_radius, color=(50, 50, 50), batch=self.batch)
        self.reload_circle_bg.opacity = 150
        self.reload_arc_segments = []
        
        # Door interaction tooltip
        self.door_tooltip = pyglet.text.Label(
            'Press SPACE to open',
            font_name='Arial', font_size=14,
            x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 100,
            anchor_x='center', anchor_y='center',
            color=(255, 255, 200, 255), batch=self.batch
        )
        self.door_tooltip.visible = False
    
    def check_connection(self):
        if self.network and not self.network.connected:
            if self.network.accept_client():
                if hasattr(self, 'connection_label'):
                    self.connection_label.text = 'Connected'
                    self.connection_label.color = GREEN
            pyglet.clock.schedule_once(lambda dt: self.check_connection(), 0.1)
    
    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.UP:
            self.arrow_keys_pressed[pyglet.window.key.UP] = True
        elif symbol == pyglet.window.key.DOWN:
            self.arrow_keys_pressed[pyglet.window.key.DOWN] = True
        elif symbol == pyglet.window.key.LEFT:
            self.arrow_keys_pressed[pyglet.window.key.LEFT] = True
        elif symbol == pyglet.window.key.RIGHT:
            self.arrow_keys_pressed[pyglet.window.key.RIGHT] = True
        elif symbol == pyglet.window.key.F:
            if self.build_menu_open:
                self.try_build()
            else:
                self.toggle_build_menu(True)
        elif self.build_menu_open:
            if symbol == pyglet.window.key._1 or symbol == pyglet.window.key.NUM_1:
                self.select_building(1)
            elif symbol == pyglet.window.key._2 or symbol == pyglet.window.key.NUM_2:
                self.select_building(2)
            elif symbol == pyglet.window.key._3 or symbol == pyglet.window.key.NUM_3:
                self.select_building(3)
        
        if symbol == pyglet.window.key.ESCAPE:
            if self.build_menu_open:
                self.toggle_build_menu(False)
    
    def on_key_release(self, symbol, modifiers):
        if symbol == pyglet.window.key.UP:
            self.arrow_keys_pressed[pyglet.window.key.UP] = False
        elif symbol == pyglet.window.key.DOWN:
            self.arrow_keys_pressed[pyglet.window.key.DOWN] = False
        elif symbol == pyglet.window.key.LEFT:
            self.arrow_keys_pressed[pyglet.window.key.LEFT] = False
        elif symbol == pyglet.window.key.RIGHT:
            self.arrow_keys_pressed[pyglet.window.key.RIGHT] = False
    
    def toggle_build_menu(self, show):
        self.build_menu_open = show
        if show:
            self.build_menu_last_used = self.game_time
        self.build_menu_bg.visible = show
        self.build_menu_title.visible = show
        self.build_menu_item1.visible = show
        self.build_menu_item2.visible = show
        self.build_menu_item3.visible = show
    
    def select_building(self, building_id):
        if building_id in self.building_types:
            self.selected_building = building_id
            self.build_menu_last_used = self.game_time
    
    def try_build(self):
        if self.selected_building not in self.building_types:
            return
        
        self.build_menu_last_used = self.game_time
        
        building = self.building_types[self.selected_building]
        cost = building['cost']
        resource = building['resource']
        
        player_comp = self.player_entity.get_component(PlayerComponent)
        player_pos = self.player_entity.get_component(PositionComponent)
        player_size = self.player_entity.get_component(SizeComponent)
        
        if resource == 'wood' and player_comp.wood >= cost:
            player_center_x = player_pos.x + player_size.width / 2
            player_center_y = player_pos.y + player_size.height / 2
            grid_x, grid_y = snap_to_grid(player_center_x, player_center_y)
            
            build_rect = (grid_x - WALL_SIZE // 2, grid_y - WALL_SIZE // 2, WALL_SIZE, WALL_SIZE)
            can_build = True
            
            # Check existing buildings and obstacles
            for entity in self.world.get_entities_with(WallComponent, PositionComponent, SizeComponent):
                pos = entity.get_component(PositionComponent)
                sz = entity.get_component(SizeComponent)
                if check_collision(build_rect, (pos.x - sz.width // 2, pos.y - sz.height // 2, sz.width, sz.height)):
                    can_build = False
                    break
            
            if can_build:
                for entity in self.world.get_entities_with(DoorComponent, PositionComponent, SizeComponent):
                    pos = entity.get_component(PositionComponent)
                    sz = entity.get_component(SizeComponent)
                    if check_collision(build_rect, (pos.x - sz.width // 2, pos.y - sz.height // 2, sz.width, sz.height)):
                        can_build = False
                        break
            
            if can_build:
                for entity in self.world.get_entities_with(StairsComponent, PositionComponent, SizeComponent):
                    pos = entity.get_component(PositionComponent)
                    sz = entity.get_component(SizeComponent)
                    if check_collision(build_rect, (pos.x - sz.width // 2, pos.y - sz.height // 2, sz.width, sz.height)):
                        can_build = False
                        break
            
            if can_build:
                for entity in self.world.get_entities_with(RockComponent, PositionComponent, SizeComponent):
                    pos = entity.get_component(PositionComponent)
                    sz = entity.get_component(SizeComponent)
                    if check_collision(build_rect, (pos.x, pos.y, sz.width, sz.height)):
                        can_build = False
                        break
            
            if can_build:
                building_type = building.get('type', 'wall')
                if building_type == 'wall':
                    create_wall(self.world, grid_x, grid_y, self.player_entity.id)
                    player_comp.wood -= cost
                elif building_type == 'door':
                    create_door(self.world, grid_x, grid_y, self.player_entity.id)
                    player_comp.wood -= cost
                elif building_type == 'stairs':
                    # Get player height level
                    player_height = self.player_entity.get_component(HeightComponent)
                    current_level = player_height.level if player_height else 0
                    
                    # Find closest obstacle with higher level
                    target_entity = None
                    min_dist = float('inf')
                    for entity in self.world.get_entities_with(PositionComponent, SizeComponent, HeightComponent):
                        entity_height = entity.get_component(HeightComponent)
                        if not entity_height or entity_height.level <= current_level:
                            continue
                        
                        entity_pos = entity.get_component(PositionComponent)
                        entity_size = entity.get_component(SizeComponent)
                        entity_center_x = entity_pos.x
                        entity_center_y = entity_pos.y
                        
                        dx = entity_center_x - grid_x
                        dy = entity_center_y - grid_y
                        dist = math.sqrt(dx**2 + dy**2)
                        
                        if dist < min_dist:
                            min_dist = dist
                            target_entity = entity
                    
                    # Calculate direction towards target (or default direction if no target)
                    if target_entity:
                        target_pos = target_entity.get_component(PositionComponent)
                        dir_x = target_pos.x - grid_x
                        dir_y = target_pos.y - grid_y
                        dir_length = math.sqrt(dir_x**2 + dir_y**2)
                        if dir_length > 0:
                            dir_x /= dir_length
                            dir_y /= dir_length
                        else:
                            dir_x, dir_y = 1.0, 0.0
                    else:
                        dir_x, dir_y = 1.0, 0.0  # Default direction
                    
                    target_level = current_level + 1
                    if target_entity:
                        target_height = target_entity.get_component(HeightComponent)
                        if target_height:
                            target_level = target_height.level
                    
                    create_stairs(self.world, grid_x, grid_y, dir_x, dir_y, current_level, target_level, self.player_entity.id)
                    player_comp.wood -= cost
    
    def try_shoot(self, dt):
        current_time = self.game_time
        if current_time - self.last_fire_time < PROJECTILE_FIRE_RATE:
            return
        
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
        
        if direction_x != 0 or direction_y != 0:
            player_pos = self.player_entity.get_component(PositionComponent)
            player_size = self.player_entity.get_component(SizeComponent)
            player_comp = self.player_entity.get_component(PlayerComponent)
            
            player_center_x = player_pos.x + player_size.width / 2
            player_center_y = player_pos.y + player_size.height / 2
            
            create_projectile(
                self.world,
                player_center_x - PROJECTILE_SIZE / 2,
                player_center_y - PROJECTILE_SIZE / 2,
                direction_x * 100, direction_y * 100,
                self.my_player_id,
                player_comp.velocity_x, player_comp.velocity_y
            )
            self.last_fire_time = current_time
    
    def update_day_night_cycle(self):
        if not self.is_night:
            time_remaining = DAY_LENGTH - self.cycle_time
            
            if time_remaining <= 5.0 and time_remaining > 0:
                self.night_warning.visible = True
                self.night_warning.text = f'NIGHT APPROACHES IN {int(time_remaining) + 1}...'
            else:
                self.night_warning.visible = False
            
            if self.cycle_time >= DAY_LENGTH:
                self.is_night = True
                self.cycle_time = 0.0
                self.night_warning.visible = False
                self.night_warning.text = 'NIGHT HAS FALLEN!'
                self.night_warning.visible = True
                self.night_warning_timer = 2.0
            
            mins = int(time_remaining // 60)
            secs = int(time_remaining % 60)
            self.time_label.text = f'Day - {mins}:{secs:02d} until night'
            self.time_label.color = (255, 255, 150, 255)
            self.day_label.color = (255, 200, 50, 255)
        else:
            time_remaining = NIGHT_LENGTH - self.cycle_time
            
            if self.cycle_time >= NIGHT_LENGTH:
                self.is_night = False
                self.cycle_time = 0.0
                self.day_count += 1
                self.night_warning.text = 'DAWN BREAKS!'
                self.night_warning.visible = True
                self.night_warning_timer = 2.0
            
            mins = int(time_remaining // 60)
            secs = int(time_remaining % 60)
            self.time_label.text = f'Night - {mins}:{secs:02d} until dawn'
            self.time_label.color = (200, 100, 100, 255)
            self.day_label.color = (150, 150, 200, 255)
        
        self.day_label.text = f'Day {self.day_count}'
        
        if self.night_warning_timer > 0:
            self.night_warning_timer -= 1.0 / FPS
            if self.night_warning_timer <= 0:
                self.night_warning.visible = False
    
    def update(self, dt):
        if not self.game_active:
            return
        
        self.frame_count += 1
        self.game_time += dt
        self.cycle_time += dt
        self.update_day_night_cycle()
        self._update_lighting(dt)  # Update lighting smoothly
        
        # Update camera to follow player
        player_pos = self.player_entity.get_component(PositionComponent)
        player_size = self.player_entity.get_component(SizeComponent)
        player_center_x = player_pos.x + player_size.width / 2
        player_center_y = player_pos.y + player_size.height / 2
        self.world.camera.update(player_center_x, player_center_y)
        
        # Handle networking
        if self.is_multiplayer and self.network and self.network.connected:
            player_comp = self.player_entity.get_component(PlayerComponent)
            self.network.send_data({
                'type': 'player_update',
                'player': {'id': player_comp.player_id, 'x': player_pos.x, 'y': player_pos.y}
            })
            
            messages = self.network.receive_data_non_blocking()
            for data in messages:
                if data.get('type') == 'player_update' and self.other_player_entity:
                    other_data = data.get('player', {})
                    other_player_comp = self.other_player_entity.get_component(PlayerComponent)
                    if other_data.get('id') == other_player_comp.player_id:
                        other_pos = self.other_player_entity.get_component(PositionComponent)
                        other_pos.x = other_data['x']
                        other_pos.y = other_data['y']
                elif data.get('type') == 'projectile':
                    if data.get('owner_id') != self.my_player_id:
                        create_projectile(
                            self.world, data['x'], data['y'],
                            data['dx'] * PROJECTILE_SPEED, data['dy'] * PROJECTILE_SPEED,
                            data['owner_id']
                        )
                elif data.get('type') == 'enemy_spawn' and not self.is_host:
                    create_enemy(self.world, data['x'], data['y'], data.get('id'))
        
        # Update ECS world (runs all systems)
        self.world.update(dt)
        
        # Try to shoot
        self.try_shoot(dt)
        
        # Auto-hide build menu after inactivity
        if self.build_menu_open and (self.game_time - self.build_menu_last_used) > 3.0:
            self.toggle_build_menu(False)
        
        # Enemy spawning (only at night)
        if self.is_night and (not self.is_multiplayer or (self.is_host and self.network and self.network.connected)):
            night_spawn_multiplier = NIGHT_SPAWN_MULTIPLIER_BASE + (self.day_count - 1) * NIGHT_SPAWN_MULTIPLIER_PER_DAY
            night_max_enemies = min(NIGHT_MAX_ENEMIES_BASE + (self.day_count - 1) * NIGHT_MAX_ENEMIES_PER_DAY, MAX_ENEMIES)
            
            base_frames_per_spawn = INITIAL_ENEMY_SPAWN_RATE - (self.cycle_time * ENEMY_SPAWN_ACCELERATION * night_spawn_multiplier)
            frames_per_spawn = max(MIN_ENEMY_SPAWN_RATE, base_frames_per_spawn)
            spawn_interval = frames_per_spawn / FPS / night_spawn_multiplier
            
            current_enemies = len(self.world.get_entities_with(EnemyComponent))
            
            self.enemy_spawn_timer += dt
            if current_enemies < night_max_enemies and self.enemy_spawn_timer >= spawn_interval:
                obstacles = self.world.get_entities_with(CollisionComponent, PositionComponent, SizeComponent)
                obstacles = [e for e in obstacles if e.get_component(CollisionComponent).layer == "obstacle"]
                enemy = spawn_enemy_ecs(self.world, player_center_x, player_center_y, obstacles)
                self.enemy_spawn_timer = 0.0
                
                if self.is_multiplayer and self.network and self.network.connected:
                    enemy_comp = enemy.get_component(EnemyComponent)
                    enemy_pos = enemy.get_component(PositionComponent)
                    self.network.send_data({
                        'type': 'enemy_spawn',
                        'x': enemy_pos.x, 'y': enemy_pos.y, 'id': enemy_comp.enemy_id
                    })
        
        # Update UI
        player_comp = self.player_entity.get_component(PlayerComponent)
        enemy_count = len(self.world.get_entities_with(EnemyComponent))
        self.score_label.text = str(enemy_count)
        self.wood_label.text = str(player_comp.wood)
        self.coin_label.text = str(player_comp.coins)
        
        # Update reload indicator
        time_since_last_shot = self.game_time - self.last_fire_time
        reload_progress = min(1.0, time_since_last_shot / PROJECTILE_FIRE_RATE)
        
        screen_x, screen_y = self.world.camera.world_to_screen(player_center_x, player_center_y)
        reload_x = screen_x + player_size.width // 2 + self.reload_circle_radius + 2
        reload_y = screen_y + player_size.height // 2 + self.reload_circle_radius + 2
        
        self.reload_circle_bg.x = reload_x
        self.reload_circle_bg.y = reload_y
        
        if reload_progress >= 1.0:
            self.reload_circle_bg.visible = False
            self._clear_reload_arc()
        else:
            self.reload_circle_bg.visible = True
            self._update_reload_arc(reload_x, reload_y, reload_progress)
    
    def _clear_reload_arc(self):
        for segment in self.reload_arc_segments:
            segment.delete()
        self.reload_arc_segments.clear()
    
    def _update_reload_arc(self, center_x, center_y, progress):
        self._clear_reload_arc()
        
        if progress <= 0:
            return
        
        num_segments = max(24, int(48 * progress))
        angle_range = 2 * math.pi * progress
        start_angle = -math.pi / 2
        
        for i in range(num_segments):
            angle = start_angle + (angle_range * i / num_segments)
            x = center_x + self.reload_circle_radius * math.cos(angle)
            y = center_y + self.reload_circle_radius * math.sin(angle)
            
            segment = shapes.Rectangle(x - 1, y - 1, 2, 2, color=(255, 255, 0), batch=self.batch)
            segment.opacity = 150
            self.reload_arc_segments.append(segment)
    
    def _update_lighting(self, dt):
        """Update lighting color smoothly with interpolation."""
        # Calculate target color based on current cycle state
        if self.is_night:
            night_progress = self.cycle_time / NIGHT_LENGTH
            if night_progress < 0.5:
                # Getting darker
                intensity = 0.05 - (night_progress * 0.05)
            else:
                # Getting lighter near dawn
                intensity = (night_progress - 0.5) * 0.1
            self.target_bg_color = [intensity * 0.3, intensity * 0.3, intensity * 0.8, 1.0]
        else:
            day_progress = self.cycle_time / DAY_LENGTH
            if day_progress < 0.15:
                # Dawn - orange/yellow tint
                intensity = 0.1 + (day_progress / 0.15) * 0.15
                self.target_bg_color = [intensity * 0.8, intensity * 0.5, intensity * 0.2, 1.0]
            elif day_progress > 0.85:
                # Dusk - orange/red tint
                dusk_progress = (day_progress - 0.85) / 0.15
                intensity = 0.25 - (dusk_progress * 0.15)
                self.target_bg_color = [intensity * 0.8, intensity * 0.4, intensity * 0.2, 1.0]
            else:
                # Midday
                self.target_bg_color = [0.08, 0.08, 0.12, 1.0]
        
        # Smoothly interpolate current color towards target (lerp factor controls smoothness)
        lerp_factor = min(1.0, dt * 2.0)  # Adjust multiplier for transition speed (2.0 = ~0.5s transition)
        for i in range(4):
            self.current_bg_color[i] = self.current_bg_color[i] + (self.target_bg_color[i] - self.current_bg_color[i]) * lerp_factor
    
    def on_draw(self):
        gl.glClearColor(*self.current_bg_color)
        self.clear()
        self.batch.draw()
    
    def show_game_over(self):
        self.game_active = False
        game_over = GameOverWindow(
            day_count=self.day_count,
            is_multiplayer=self.is_multiplayer,
            is_host=self.is_host,
            host_ip=self.host_ip
        )
        ScreenManager.set_window(game_over)
    
    def on_close(self):
        self.game_active = False
        pyglet.clock.unschedule(self.update)
        self._clear_reload_arc()
        self.world.clear()
        if self.network:
            self.network.close()
        super().on_close()

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    menu = MenuWindow()
    ScreenManager.set_window(menu)
    pyglet.app.run()

if __name__ == "__main__":
    main()
