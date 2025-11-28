# Cube Shooter Game

A simple 2D game where you control a blue cube that can move around and shoot projectiles at enemies.

## Features

- **Player Control**: Move your green cube using W, A, S, D keys
- **Shooting**: Press ARROW KEYS to shoot yellow projectiles in that direction
- **Sprint**: Hold SPACEBAR to sprint at 2x speed (uses sprint energy)
- **Sprint Bar**: Sprint energy slowly recharges over time - use it wisely!
- **Enemies**: Red enemy cubes spawn randomly from the edges and chase you
- **Dynamic Difficulty**: Enemy spawn rate increases over time
- **Combat**: Enemies disappear when hit by projectiles

## Installation

1. Make sure you have Python 3.7+ installed (works with Python 3.14+)
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## How to Run

```bash
python game.py
```

## Controls

- **W** / **↑**: Move up
- **A** / **←**: Move left
- **S** / **↓**: Move down
- **D** / **→**: Move right
- **Arrow Keys** (↑ ↓ ← →): Fire projectiles in the direction of the arrow key pressed
- **SPACEBAR** (Hold): Sprint at 2x speed (consumes sprint energy shown in the bar)

## Game Rules

- The game ends when an enemy collides with the player
- Try to survive as long as possible by shooting enemies before they reach you!
- Enemies continuously spawn from the edges of the screen

## Technical Notes

This game uses `pyglet` instead of `pygame` for better compatibility with Python 3.14+. Pyglet is a modern, lightweight game library that works seamlessly with the latest Python versions.

## Enjoy!

Have fun playing the game!
