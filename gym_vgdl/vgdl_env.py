import gym
from gym import spaces
import vgdl.core as core
import pygame
import numpy as np


class VGDLEnv(gym.Env):
    metadata = {
        'render.modes': ['human', 'rgb_array'],
        'video.frames_per_second': 25
    }

    def __init__(self, game_file = None, map_file = None, obs_type = 'image'):

        # Load game description and level description
        if game_file == None:
            self.game_desc = aliens_game
            self.level_desc = aliens_level
        else:
            with open (game_file, "r") as myfile:
                self.game_desc = myfile.read()
            with open (map_file, "r") as myfile:
                self.level_desc = myfile.read()


        self._obs_type = obs_type
        self.viewer = None
        
        # Need to build a sample level to get the available actions and screensize....
        self.game = core.VGDLParser().parseGame(self.game_desc)
        self.game.buildLevel(self.level_desc)

        self._action_set = self.game.getPossibleActions()
        self.screen_width, self.screen_height = self.game.screensize

        self.score_last = self.game.score

        # Set action space and observation space

        self.action_space = spaces.Discrete(len(self._action_set))
        if self._obs_type == 'image':
            self.observation_space = spaces.Box(low=0, high=255, shape=(self.screen_width, self.screen_height, 3))
        elif self._obs_type == 'objects':
            self.observation_space = []#spaces.List()

        self.screen = pygame.display.set_mode(self.game.screensize, 0, 32)



    def _step(self, a):
        self.game.tick(self._action_set.values()[a], True)
        state = self._get_obs()
        reward = self.game.score - self.score_last; self.score_last = self.game.score
        terminal = self.game.ended

        return state, reward, terminal, {}


    @property
    def _n_actions(self):
        return len(self._action_set)

    def _get_image(self):
        return np.flipud(np.rot90(pygame.surfarray.array3d(
            pygame.display.get_surface()).astype(np.uint8)))

    def _get_obs(self):
        if self._obs_type == 'image':
            return self._get_image()
        elif self._obs_type == 'objects':
            return self.game.getObservation()

    def _reset(self):

        # Do things the easy way...
        del self.game
        self.game = core.VGDLParser().parseGame(self.game_desc)
        self.game.buildLevel(self.level_desc)

        self.game.screen = self.screen
        self.game.background = pygame.Surface(self.game.screensize)
        self.game.screen.fill((0, 0, 0))

        self.score_last = self.game.score

        state = self._get_obs()

        return state

    def _render(self, mode='human', close=False):
        if close:
            if self.viewer is not None:
                self.viewer.close()
                self.viewer = None
            return
        img = self._get_image()
        if mode == 'rgb_array':
            return img
        elif mode == 'human':
            from gym.envs.classic_control import rendering
            if self.viewer is None:
                self.viewer = rendering.SimpleImageViewer()
            self.viewer.imshow(img)


####################################################################################################


# Example VGDL description text
# The game dynamics are specified as a paragraph of text

aliens_game = """
BasicGame block_size=10
    SpriteSet
        background > Immovable img=oryx/space1 hidden=True
        base    > Immovable    color=WHITE img=oryx/planet
        avatar  > FlakAvatar   stype=sam img=oryx/spaceship1
        missile > Missile
            sam  > orientation=UP    color=BLUE singleton=True img=oryx/bullet2
            bomb > orientation=DOWN  color=RED  speed=0.5 img=oryx/bullet2
        alien   > Bomber       stype=bomb   prob=0.05  cooldown=3 speed=0.8
            alienGreen > img=oryx/alien3
            alienBlue > img=oryx/alien1
        portal  > invisible=True hidden=True
        	portalSlow  > SpawnPoint   stype=alienBlue  cooldown=16   total=20
        	portalFast  > SpawnPoint   stype=alienGreen  cooldown=12   total=20
    
    LevelMapping
        . > background
        0 > background base
        1 > background portalSlow
        2 > background portalFast
        A > background avatar

    TerminationSet
        SpriteCounter      stype=avatar               limit=0 win=False
        MultiSpriteCounter stype1=portal stype2=alien limit=0 win=True
        
        
    InteractionSet
        avatar  EOS  > stepBack
        alien   EOS  > turnAround
        missile EOS  > killSprite

        base bomb > killSprite
        base sam > killSprite scoreChange=1

        base   alien > killSprite
        avatar alien > killSprite scoreChange=-1
        avatar bomb  > killSprite scoreChange=-1
        alien  sam   > killSprite scoreChange=2     
"""

# the (initial) level as a block of characters 
aliens_level = """
1.............................
000...........................
000...........................
..............................
..............................
..............................
..............................
....000......000000.....000...
...00000....00000000...00000..
...0...0....00....00...00000..
................A.............
"""
