'''
Video game description language -- parser, framework and core game classes.

@author: Tom Schaul
'''

import pygame
import random
from tools import Node, indentTreeParser
from collections import defaultdict
from tools import roundedPoints
import os
import sys


class VGDLParser(object):
    """ Parses a string into a Game object. """
    verbose = False

    def parseGame(self, tree):
        """ Accepts either a string, or a tree. """
        if not isinstance(tree, Node):
            tree = indentTreeParser(tree).children[0]
        sclass, args = self._parseArgs(tree.content)
        self.game = sclass(**args)
        for c in tree.children:
            if c.content == "SpriteSet":
                self.parseSprites(c.children)
            if c.content == "InteractionSet":
                self.parseInteractions(c.children)
            if c.content == "LevelMapping":
                self.parseMappings(c.children)
            if c.content == "TerminationSet":
                self.parseTerminations(c.children)
        return self.game

    def _eval(self, estr):
        """ Whatever is visible in the global namespace (after importing the ontologies)
        can be used in the VGDL, and is evaluated.
        """
        from ontology import * #@UnusedWildImport
        return eval(estr)

    def parseInteractions(self, inodes):
        for inode in inodes:
            if ">" in inode.content:
                pair, edef = [x.strip() for x in inode.content.split(">")]
                eclass, args = self._parseArgs(edef)
                self.game.collision_eff.append(tuple([x.strip() for x in pair.split(" ") if len(x)>0]
                                                     +[eclass, args]))
                if self.verbose:
                    print "Collision", pair, "has effect:", edef

    def parseTerminations(self, tnodes):
        for tn in tnodes:
            sclass, args = self._parseArgs(tn.content)
            if self.verbose:
                print "Adding:", sclass, args
            self.game.terminations.append(sclass(**args))

    def parseSprites(self, snodes, parentclass=None, parentargs={}, parenttypes=[]):
        for sn in snodes:
            assert ">" in sn.content
            key, sdef = [x.strip() for x in sn.content.split(">")]
            sclass, args = self._parseArgs(sdef, parentclass, parentargs.copy())
            stypes = parenttypes+[key]
            if 'singleton' in args:
                if args['singleton']==True:
                    self.game.singletons.append(key)
                args = args.copy()
                del args['singleton']

            if len(sn.children) == 0:
                if self.verbose:
                    print "Defining:", key, sclass, args, stypes
                self.game.sprite_constr[key] = (sclass, args, stypes)
                if key in self.game.sprite_order:
                    # last one counts
                    self.game.sprite_order.remove(key)
                self.game.sprite_order.append(key)
            else:
                self.parseSprites(sn.children, sclass, args, stypes)

    def parseMappings(self, mnodes):
        for mn in mnodes:
            c, val = [x.strip() for x in mn.content.split(">")]
            assert len(c) == 1, "Only single character mappings allowed."
            # a char can map to multiple sprites
            keys = [x.strip() for x in val.split(" ") if len(x)>0]
            if self.verbose:
                print "Mapping", c, keys
            self.game.char_mapping[c] = keys

    def _parseArgs(self, s,  sclass=None, args=None):
        if not args:
            args = {}
        sparts = [x.strip() for x in s.split(" ") if len(x) > 0]
        if len(sparts) == 0:
            return sclass, args
        if not '=' in sparts[0]:
            sclass = self._eval(sparts[0])
            sparts = sparts[1:]
        for sp in sparts:
            k, val = sp.split("=")
            try:
                args[k] = self._eval(val)
            except:
                args[k] = val
        return sclass, args


class BasicGame(object):
    """ This regroups all the components of a game's dynamics, after parsing. """
    MAX_SPRITES = 10000

    default_mapping = {'w': ['wall'],
                       'A': ['avatar'],
                       }

    seed = 123
    block_size = 10
    frame_rate = 25
    load_save_enabled = True

    def __init__(self, **kwargs):
        from ontology import Immovable, DARKGRAY, MovingAvatar, GOLD
        for name, value in kwargs.iteritems():
            if hasattr(self, name):
                self.__dict__[name] = value
            else:
                print "WARNING: undefined parameter '%s' for game! "%(name)

        # contains mappings to constructor (just a few defaults are known)
        self.sprite_constr = {'wall': (Immovable, {'color': DARKGRAY}, ['wall']),
                              'avatar': (MovingAvatar, {}, ['avatar']),
                              }
        # z-level of sprite types (in case of overlap)
        self.sprite_order  = ['wall',
                              'avatar',
                              ]
        # contains instance lists
        self.sprite_groups = defaultdict(list)
        # which sprite types (abstract or not) are singletons?
        self.singletons = []
        # collision effects (ordered by execution order)
        self.collision_eff = []
        # for reading levels
        self.char_mapping = {}
        # termination criteria
        self.terminations = [Termination()]
        # resource properties
        self.resources_limits = defaultdict(lambda: 2)
        self.resources_colors = defaultdict(lambda: GOLD)

        self.is_stochastic = False
        self._lastsaved = None
        self.reset()


    def buildLevel(self, lstr):
        from ontology import stochastic_effects
        lines = [l for l in lstr.split("\n") if len(l)>0]
        lengths = map(len, lines)
        assert min(lengths)==max(lengths), "Inconsistent line lengths."
        self.width = lengths[0]
        self.height = len(lines)
        assert self.width > 1 and self.height > 1, "Level too small."
        # rescale pixels per block to adapt to the level
        #self.block_size = max(2,int(800./max(self.width, self.height)))
        self.screensize = (self.width*self.block_size, self.height*self.block_size)

        # set up resources
        for res_type, (sclass, args, _) in self.sprite_constr.iteritems():
            if issubclass(sclass, Resource):
                if 'res_type' in args:
                    res_type = args['res_type']
                if 'color' in args:
                    self.resources_colors[res_type] = args['color']
                if 'limit' in args:
                    self.resources_limits[res_type] = args['limit']

        # create sprites
        for row, l in enumerate(lines):
            for col, c in enumerate(l):
                if c in self.char_mapping:
                    pos = (col*self.block_size, row*self.block_size)
                    self._createSprite(self.char_mapping[c], pos)
                elif c in self.default_mapping:
                    pos = (col*self.block_size, row*self.block_size)
                    self._createSprite(self.default_mapping[c], pos)
        self.kill_list=[]
        for _, _, effect, _ in self.collision_eff:
            if effect in stochastic_effects:
                self.is_stochastic = True

        # guarantee that avatar is always visible
        self.sprite_order.remove('avatar')
        self.sprite_order.append('avatar')


    # Resets... basically nothing
    def reset(self):
        self.score = 0
        self.time = 0
        self.ended = False
        self.num_sprites = 0
        self.kill_list=[]
        self.random_generator = random.Random(self.seed)


    # Returns a list of empty grid cells
    def emptyBlocks(self):
        alls = [s for s in self]
        res = []
        for col in range(self.width):
            for row in range(self.height):
                r = pygame.Rect((col*self.block_size, row*self.block_size), (self.block_size, self.block_size))
                free = True
                for s in alls:
                    if r.colliderect(s.rect):
                        free = False
                        break
                if free:
                    res.append((col*self.block_size, row*self.block_size))
        return res

    def randomizeAvatar(self):
        if len(self.getAvatars()) == 0:
            self._createSprite(['avatar'], self.random_generator.choice(self.emptyBlocks()))

    
    def _createSprite(self, keys, pos):
        res = []
        for key in keys:
            if self.num_sprites > self.MAX_SPRITES:
                print "Sprite limit reached."
                return
            sclass, args, stypes = self.sprite_constr[key]
            # verify the singleton condition
            anyother = False
            for pk in stypes[::-1]:
                if pk in self.singletons:
                    if self.numSprites(pk) > 0:
                        anyother = True
                        break
            if anyother:
                continue
            s = sclass(pos=pos, size=(self.block_size, self.block_size), name=key, **args)
            s.stypes = stypes
            self.sprite_groups[key].append(s)
            self.num_sprites += 1
            if s.is_stochastic:
                self.is_stochastic = True
            res.append(s)
        return res

    def _createSprite_cheap(self, key, pos):
        """ The same, but without the checks, which speeds things up during load/saving"""
        sclass, args, stypes = self.sprite_constr[key]
        s = sclass(pos=pos, size=(self.block_size, self.block_size), name=key, **args)
        s.stypes = stypes
        self.sprite_groups[key].append(s)
        self.num_sprites += 1
        return s

    def __iter__(self):
        """ Iterator over all sprites (ordered) """
        for key in self.sprite_order:
            if key not in self.sprite_groups:
                # abstract type
                continue
            for s in self.sprite_groups[key]:
                yield s

    def numSprites(self, key):
        """ Abstract sprite groups are computed on demand only """
        deleted = len([s for s in self.kill_list if key in s.stypes])
        if key in self.sprite_groups:
            return len(self.sprite_groups[key])-deleted
        else:
            return len([s for s in self if key in s.stypes])-deleted

    def getSprites(self, key):
        if key in self.sprite_groups:
            return [s for s in self.sprite_groups[key] if s not in self.kill_list]
        else:
            return [s for s in self if key in s.stypes and s not in self.kill_list]

    def getAvatars(self):
        """ The currently alive avatar(s) """
        res = []
        for ss in self.sprite_groups.values():
            if ss and isinstance(ss[0], Avatar):
                res.extend([s for s in ss if s not in self.kill_list])
        return res

    ignoredattributes = ['stypes',
                             'name',
                             'lastmove',
                             'color',
                             'lastrect',
                             'resources',
                             'physicstype',
                             'physics',
                             'rect',
                             'alternate_keys',
                             'res_type',
                             'stype',
                             'ammo',
                             'draw_arrow',
                             'shrink_factor',
                             'prob',
                             'is_stochastic',
                             'cooldown',
                             'total',
                             'is_static',
                             'noiseLevel',
                             'angle_diff',
                             'only_active',
                             'airsteering',
                             'strength',
                             'img',
                             'image',
                             'scale_image',
                             'randomtiling',
                             ]


    # Returns gamestate in observation format
    def getObservation(self):
        from ontology import Avatar, Immovable, Missile, Portal, RandomNPC, ResourcePack
        state = []
        for key in self.sprite_groups:
            for s in self.getSprites(key):
                if (key != 'background') & (key != 'portalSlow'):
                    pos = (float(s.rect.left), float(s.rect.top)) #s.speed
                    if hasattr(s, 'orientation'):
                        orient = s.orientation
                    else:
                        orient = [0,0]
                    #obs = [ key, pos, isinstance(s,Avatar), isinstance(s,Immovable), isinstance(s,Portal), isinstance(s,RandomNPC), isinstance(s,ResourcePack)]
                    obs = [ pos[0]/self.block_size, pos[1]/self.block_size, float(orient[0]), float(orient[1]), float(isinstance(s,Avatar)),
                            float(isinstance(s,Immovable)), float(isinstance(s,RandomNPC)), float(isinstance(s,Missile))] #x6
                    state.append(obs)
        return state


    # Clears sprite from screen and removes dead sprites
    def _clearAll(self, onscreen=True):
        for s in set(self.kill_list):
            if onscreen:
                s._clear(self.screen, self.background, double=True)
            self.sprite_groups[s.name].remove(s)
        if onscreen:
            for s in self:
                s._clear(self.screen, self.background)
        self.kill_list = []

    def _drawAll(self):
        for s in self:
            s._draw(self)

    def _updateCollisionDict(self, changedsprite):
        for key in changedsprite.stypes:
            if key in self.lastcollisions:
                del self.lastcollisions[key]

    def _eventHandling(self):
        self.lastcollisions = {}
        ss = self.lastcollisions
        for g1, g2, effect, kwargs in self.collision_eff:
            # build the current sprite lists (if not yet available)
            for g in [g1, g2]:
                if g not in ss:
                    if g in self.sprite_groups:
                        tmp = self.sprite_groups[g]
                    else:
                        tmp = []
                        for key in self.sprite_groups:
                            v = self.sprite_groups[key]
                            if v and g in v[0].stypes:
                                tmp.extend(v)
                    ss[g] = (tmp, len(tmp))

            # special case for end-of-screen
            if g2 == "EOS":
                ss1, l1 = ss[g1]
                for s1 in ss1:
                    if not pygame.Rect((0,0), self.screensize).contains(s1.rect):
                        effect(s1, None, self, **kwargs)
                continue

            # iterate over the shorter one
            ss1, l1 = ss[g1]
            ss2, l2 = ss[g2]
            if l1 < l2:
                shortss, longss, switch = ss1, ss2, False
            else:
                shortss, longss, switch = ss2, ss1, True

            # score argument is not passed along to the effect function
            score = 0
            if 'scoreChange' in kwargs:
                kwargs = kwargs.copy()
                score = kwargs['scoreChange']
                del kwargs['scoreChange']

            # do collision detection
            for s1 in shortss:
                for ci in s1.rect.collidelistall(longss):
                    s2 = longss[ci]
                    if s1 == s2:
                        continue
                    # deal with the collision effects
                    if score:
                        self.score += score
                    if switch:
                        # CHECKME: this is not a bullet-proof way, but seems to work
                        if s2 not in self.kill_list:
                            effect(s2, s1, self, **kwargs)
                    else:
                        # CHECKME: this is not a bullet-proof way, but seems to work
                        if s1 not in self.kill_list:
                            effect(s1, s2, self, **kwargs)


    def getPossibleActions(self):
        return self.getAvatars()[0].declare_possible_actions()


    def tick(self, action, render = True):

        # This is required for game-updates to work properly
        self.time += 1

        # Flush events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        # Update Keypresses
        # Agents are updated during the update routine in their ontology files, this demends on BasicGame.keystate
        self.keystate = [0]*323 #323 seems to be the magic number..... (try len(pygame.key.get_pressed()))
        self.keystate[action] = True

	# Iterate Over Termination Criteria
	for t in self.terminations:
	    self.ended, win = t.isDone(self)
	    if self.ended:
	        break

        if self.time > 1000:
            self.ended = True

	# Update Sprites
	for s in self:
	    s.update(self)
	# Handle Collision Effects
	self._eventHandling()

        # Clean up dead sprites
        self._clearAll()
        
        if render:
	    self._drawAll()
            pygame.display.update()



class VGDLSprite(object):
    """ Base class for all sprite types. """
    name = None
    COLOR_DISC = [20,80,140,200]
    dirtyrects = []

    is_static= False
    only_active =False
    is_avatar= False
    is_stochastic = False
    color    = None
    cooldown = 0 # pause ticks in-between two moves
    speed    = None
    mass     = 1
    physicstype=None
    shrinkfactor=0

    def __init__(self, pos, size=(10,10), color=None, speed=None, cooldown=None, physicstype=None, **kwargs):
        from ontology import GridPhysics
        self.rect = pygame.Rect(pos, size)
        self.lastrect = self.rect
        self.physicstype = physicstype or self.physicstype or GridPhysics
        self.physics = self.physicstype()
        self.physics.gridsize = size
        self.speed = speed or self.speed
        self.cooldown = cooldown or self.cooldown
        self.img = 0
        self.color = color or self.color or (self.random_generator.choice(self.COLOR_DISC), self.random_generator.choice(self.COLOR_DISC), self.random_generator.choice(self.COLOR_DISC))

        for name, value in kwargs.iteritems():
            try:
                self.__dict__[name] = value
            except:
                print "WARNING: undefined parameter '%s' for sprite '%s'! "%(name, self.__class__.__name__)
        # how many timesteps ago was the last move?
        self.lastmove = 0

        # management of resources contained in the sprite
        self.resources = defaultdict(lambda: 0)

        # TODO: Load images into a central dictionary to save loading a separate image for each object
        if self.img:
            pth = 'sprites/' + self.img + '.png'
            self.image = pygame.image.load(os.path.join(os.path.dirname(__file__), pth))
            self.scale_image = pygame.transform.scale(self.image, (int(size[0] * (1-self.shrinkfactor)), int(size[1] * (1-self.shrinkfactor))))#.convert_alpha()


    def update(self, game):
        """ The main place where subclasses differ. """
        self.lastrect = self.rect
        # no need to redraw if nothing was updated
        self.lastmove += 1
        if not self.is_static and not self.only_active:
            self.physics.passiveMovement(self)

    def _updatePos(self, orientation, speed=None):
        if speed is None:
            speed = self.speed
        if not(self.cooldown > self.lastmove or abs(orientation[0])+abs(orientation[1])==0):
            self.rect = self.rect.move((orientation[0]*speed, orientation[1]*speed))
            self.lastmove = 0

    def _velocity(self):
        """ Current velocity vector. """
        if self.speed is None or self.speed==0 or not hasattr(self, 'orientation'):
            return (0,0)
        else:
            return (self.orientation[0]*self.speed, self.orientation[1]*self.speed)

    @property
    def lastdirection(self):
        return (self.rect[0]-self.lastrect[0], self.rect[1]-self.lastrect[1])


    def _draw(self, game):
        screen = game.screen
        if self.shrinkfactor != 0:
            shrunk = self.rect.inflate(-self.rect.width*self.shrinkfactor,
                                       -self.rect.height*self.shrinkfactor)
        else:
            shrunk = self.rect

        # uncomment for debugging
        #from ontology import LIGHTGREEN
        #rounded = roundedPoints(self.rect)
        #pygame.draw.lines(screen, self.color, True, rounded, 2)
        if self.img:
            screen.blit(self.scale_image, shrunk)
        else:
            screen.fill(self.color, shrunk)
        if self.resources:
            self._drawResources(game, screen, shrunk)
        #r = self.rect.copy()
        #VGDLSprite.dirtyrects.append(r)

    def _drawResources(self, game, screen, rect):
        """ Draw progress bars on the bottom third of the sprite """
        from ontology import BLACK
        tot = len(self.resources)
        barheight = rect.height/3.5/tot
        offset = rect.top+2*rect.height/3.
        for r in sorted(self.resources.keys()):
            wiggle = rect.width/10.
            prop = max(0,min(1,self.resources[r] / float(game.resources_limits[r])))
            filled = pygame.Rect(rect.left+wiggle/2, offset, prop*(rect.width-wiggle), barheight)
            rest   = pygame.Rect(rect.left+wiggle/2+prop*(rect.width-wiggle), offset, (1-prop)*(rect.width-wiggle), barheight)
            screen.fill(game.resources_colors[r], filled)
            screen.fill(BLACK, rest)
            offset += barheight

    def _clear(self, screen, background, double=False):
        0#r = screen.blit(background, self.rect, self.rect)
        #VGDLSprite.dirtyrects.append(r)
        #if double:
            #r = screen.blit(background, self.lastrect, self.lastrect)
            #VGDLSprite.dirtyrects.append(r)

    def __repr__(self):
        return self.name+" at (%s,%s)"%(self.rect.left, self.rect.top)


class Avatar(object):
    """ Abstract superclass of all avatars. """
    shrinkfactor=0.15

    def __init__(self):
        self.actions = self.declare_possible_actions()

class Resource(VGDLSprite):
    """ A special type of object that can be present in the game in two forms, either
    physically sitting around, or in the form of a counter inside another sprite. """
    value=1
    limit=2
    res_type = None

    @property
    def resourceType(self):
        if self.res_type is None:
            return self.name
        else:
            return self.res_type

class Termination(object):
    """ Base class for all termination criteria. """
    def isDone(self, game):
        """ returns whether the game is over, with a win/lose flag """
        from pygame.locals import K_ESCAPE, QUIT
        if game.keystate[K_ESCAPE] or pygame.event.peek(QUIT):
            return True, False
        else:
            return False, None