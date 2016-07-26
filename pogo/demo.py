#!/usr/bin/python
import argparse
import logging
import time
import heapq
import sys
import numpy as np
from custom_exceptions import GeneralPogoException

from api import PokeAuthSession
from location import Location

import valuator

import mappings


def setupLogger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('Line %(lineno)d,%(filename)s - %(asctime)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)


# Example functions
# Get profile
def getProfile(session):
        logging.info("Printing Profile:")
        profile = session.getProfile()
        logging.info(profile)


# Grab the nearest pokemon details
def findClosestPokemon(session, num_return=5):
    distances, pokemon = find_pokemon(session, sort=True, num_return=num_return)
    if len(distances) > 0:
        return pokemon[-1]
    else:
        return None

def find_pokemon(session, sort=False, num_return=5, radius=10):
    # Get Map details and print pokemon
    logging.info('Finding nearby Pokemon')
    cells = session.getMapObjects(radius=radius)
    latitude, longitude, _ = session.getCoordinates()
    p_d = []
    pokemons = [pokemon for cell in cells.map_cells for pokemon in cell.wild_pokemons]
    distances = [None] * len(pokemons)
    for ind, pokemon in enumerate(pokemons):
        # Log the pokemon found
        logging.info("Found %s at %f,%f" % (
            mappings.id_name[pokemon.pokemon_data.pokemon_id],
            pokemon.latitude,
            pokemon.longitude
        ))
        distance = Location.getDistance(
                latitude,
                longitude,
                pokemon.latitude,
                pokemon.longitude
            )
        # Finds distance to pokemon
        if sort:
            heapq.heappush(p_d, (distance, pokemon))
        else:
            distances[ind] = distance
    if sort:
        try:
            distances, pokemons = zip(*heapq.nsmallest(num_return, p_d))
        except:
            distances, pokemons = [], []
    return distances, pokemons


# Catch a pokemon at a given point
def walkAndCatch(session, pokemon):
    if pokemon:
        logging.info("Catching nearest pokemon:")
        #session.walkTo(pokemon.latitude, pokemon.longitude)
        logging.info(session.encounterAndCatch(pokemon))


# Do Inventory stuff
def getInventory(session):
    logging.info("Get Inventory:")
    logging.info(session.getInventory())


# Basic solution to spinning all forts.
# Since traveling salesman problem, not
# true solution. But at least you get
# those step in
def sortCloseForts(session, recent_forts):
    # Sort nearest forts (pokestop)
    #logging.info("Sorting Nearest Forts:")
    cells = session.getMapObjects()
    latitude, longitude, _ = session.getCoordinates()
    ordered_forts = []
    for cell in cells.map_cells:
        for fort in cell.forts:
            dist = Location.getDistance(
                latitude,
                longitude,
                fort.latitude,
                fort.longitude
            )
            if fort.type == 1:
                ordered_forts.append({'distance': dist, 'fort': fort})
    ordered_forts = sorted(ordered_forts, key=lambda k: k['distance'])
    result = [instance['fort'] for instance in ordered_forts if instance['fort'].id not in [fort.id for fort in recent_forts]]
    #print 'recent forts: ', len([fort.id for fort in recent_forts])
    #print 'current forts: ', len([fort['fort'].id for fort in ordered_forts])
    #print 'result forts: ', len([fort.id for fort in result])
    #print 'sorted closest forts: ', result
    return result


# Find the fort closest to user
def findClosestFort(session, recent_forts):
    # Find nearest fort (pokestop)
    logging.info("Finding Nearest Pokestops:")
    close_forts = sortCloseForts(session, recent_forts)
    while len(close_forts) == 0:
        latitude, longitude, _ = session.getCoordinates()
        session.walkTo(latitude + 0.02, longitude + 0.02)
        close_forts = sortCloseForts(session, recent_forts)
    return close_forts[1]


# Walk to fort and spin
def walkAndSpin(session, fort):
    # No fort, demo == over
    if fort:
        logging.info("Spinning a Fort:")
        # Walk over
        session.walkTo(fort.latitude, fort.longitude)
        # Give it a spin
        fortResponse = session.getFortSearch(fort)
        #logging.info(fortResponse)

#def ball_chooser(session, bag):
    #

def walk_and_tour(session, target_stops):
    cooldown = 1
    stop = 0
    recent_forts = []
    while stop < target_stops:
        if check_bag_full(session):
            trim_all_items(session, 10)
        closest = findClosestFort(session, recent_forts)
        if closest:
            logging.info('spun %d Pokestops so far' % stop)
            logging.info('heading to Pokestop %s located at %f, %f' % (closest.id, closest.latitude, closest.longitude))
            session.walkTo(closest.latitude, closest.longitude)
            fort_response = session.getFortSearch(closest)
            if fort_response.result == 1:
                logging.info('Pokestop spun succesfully')
                if len(recent_forts) > 0:
                    if recent_forts[0].cooldown_complete_timestamp_ms < time.time() * 1000:
                        recent_forts.pop(0)
                if hasattr(closest, 'lure_info'):
                    logging.info('Lure found!')
                    party = session.getInventory()['party']
                    if len(party) >= 160:
                        release_the_weak(session)
                    distance, pokemons = find_pokemon(session, sort=False, radius=20)
                    if len(pokemons) > 0:
                        for pokemon in pokemons:
                            if session.encounterPokemon(pokemon).status != 1:
                                logging.info('Walking to catch %s', mappings.id_name[pokemon.pokemon_data.pokemon_id])
                                session.walkTo(pokemon.latitude, pokemon.longitude)
                            bag = session.checkInventory()["bag"]
                            ball = np.argmax([bag[mappings.items[ball]] for ball in ['ITEM_' + type + '_BALL' for type in ['POKE', 'GREAT', 'ULTRA']]]) + 1
                            try:
                                catch_result = session.catchPokemon(pokemon, ball)
                                while catch_result.status not in [1, 3]:
                                    catch_result = session.catchPokemon(pokemon)
                                logging.info('%s caught a %s' % ('Successfully' if catch_result.status == 1 else 'Unsuccessfully', mappings.id_name[pokemon.pokemon_data.pokemon_id]))
                            except GeneralPogoException as e:
                                logging.critical('GeneralPogoException raised: %s', e)
                                session = poko_session.reauthenticate(session)
                                time.sleep(cooldown)
                                cooldown *= 2
                else:
                    logging.info('Not a lure!')
                stop += 1
            else:
                logging.info('Pokestop spun unsuccesfully')
            if closest not in recent_forts:
                recent_forts.append(closest)
            time.sleep(1)
        stats = session.checkInventory()['stats']
        logging.info('Level %d (%d/%d) %2.2f%% to Level %d' % (stats.level, stats.experience, stats.next_level_xp, (stats.experience - stats.prev_level_xp) / float(stats.next_level_xp - stats.prev_level_xp) * 100.0, stats.level + 1))
        logging.info('Previous xp: %d, Next xp: %d, Current xp: %d' % (stats.prev_level_xp, stats.next_level_xp, stats.experience))


# Walk and spin everywhere
def walkAndSpinMany(session, forts):
    for fort in forts:
        walkAndSpin(session, fort)


# A very brute force approach to evolving
def evolveAllPokemon(session):
    inventory = session.checkInventory()
    for pokemon in inventory["party"]:
        logging.info(session.evolvePokemon(pokemon))
        time.sleep(1)


# You probably don't want to run this
def releaseAllPokemon(session):
    inventory = session.checkInventory()
    for pokemon in inventory["party"]:
        session.releasePokemon(pokemon)
        time.sleep(1)

def release_the_weak(session):
    inventory = session.checkInventory()
    party = inventory['party']
    pokes = {}
    for poke in party:
        if poke.pokemon_id not in pokes:
            pokes[poke.pokemon_id] = [poke]
        else:
            pokes[poke.pokemon_id].append(poke)
    for id, indi_poke in pokes.items():
        if len(indi_poke) > 1:
            indi_poke.sort(key=lambda x: valuator.perfect(x.individual_attack, x.individual_defense, x.individual_stamina))
            '''
            poke = indi_poke[-1]
            print '______Best_____'
            print poke
            print valuator.perfect(poke.individual_attack, poke.individual_defense, poke.individual_stamina)
            poke = indi_poke[0]
            print '______Worst_____'
            print poke
            print valuator.perfect(poke.individual_attack, poke.individual_defense, poke.individual_stamina)
            '''
            for poke in indi_poke[:-1]:
                session.releasePokemon(poke)
                logging.info('Releasing %s (%d|%d|%d)' % (mappings.id_name[poke.pokemon_id], poke.individual_attack, poke.individual_defense, poke.individual_stamina))
                time.sleep(1)


def check_bag_full(session):
    bag = session.checkInventory()['bag']
    if sum(bag.values()) >= 350:
        return True
    else:
        return False

# Just incase you didn't want any revives
def tossRevives(session):
    bag = session.checkInventory()["bag"]
    # 201 are revives.
    # TODO: We should have a reverse lookup here
    return session.recycleItem(201, bag[201])

def trim_items(session, item, number_to_have):
    bag = session.checkInventory()['bag']
    if type(item) is not int:
        item_id = mappings.items[item]
    else:
        item_id = item
    if bag[item_id] > number_to_have:
        return session.recycleItem(item_id, bag[item_id] - number_to_have)

def trim_all_items(session, number_to_have, semi_priviledged_items = ['ITEM_ULTRA_BALL', 'ITEM_HYPER_POTION', 'ITEM_MAX_REVIVE'], priviledged_items=['ITEM_LUCKY_EGG', 'ITEM_INCENSE_ORDINARY', 'ITEM_SPECIAL_CAMERA', 'ITEM_INCUBATOR_BASIC', 'ITEM_INCUBATOR_BASIC_UNLIMITED', 'ITEM_TROY_DISK']):
    priviledged_items = [mappings.items[item] for item in priviledged_items]
    semi_priviledged_items = [mappings.items[item] for item in semi_priviledged_items]
    bag = session.checkInventory()['bag']
    prev_sum = sum(bag.values())
    for item_id, count in bag.items():
        if item_id in semi_priviledged_items:
            trim_items(session, item_id, count - 5)
        elif item_id not in priviledged_items:
            trim_items(session, item_id, number_to_have)
    bag = session.checkInventory()['bag']
    logging.info('Threw away %d items' % int(prev_sum - sum(bag.values())))


def check_incubators(session):
    inventory = session.checkInventory()

# Set an egg to an incubator
def setEgg(session):
    inventory = session.checkInventory()

    # If no eggs, nothing we can do
    if len(inventory["eggs"]) == 0:
        return None

    egg = inventory["eggs"][0]
    incubator = inventory["incubators"][0]
    return session.setEgg(incubator, egg)


# Basic bot
def simpleBot(session):
    # Trying not to flood the servers
    cooldown = 1

    # Run the bot
    while True:
        try:
            forts = sortCloseForts(session)
            for fort in forts:
                pokemon = findClosestPokemon(session)
                walkAndCatch(session, pokemon)
                walkAndSpin(session, fort)
                cooldown = 1
                time.sleep(1)

        # Catch problems and reauthenticate
        except GeneralPogoException as e:
            logging.critical('GeneralPogoException raised: %s', e)
            session = poko_session.reauthenticate(session)
            time.sleep(cooldown)
            cooldown *= 2

        except Exception as e:
            logging.critical('Exception raised: %s', e)
            session = poko_session.reauthenticate(session)
            time.sleep(cooldown)
            cooldown *= 2

# Entry point
# Start off authentication and demo
if __name__ != '__main__':
    setupLogger()
    logging.debug('Logger set up')

    # Read in args
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--auth", help="Auth Service", required=True)
    parser.add_argument("-u", "--username", help="Username", required=True)
    parser.add_argument("-p", "--password", help="Password", required=True)
    parser.add_argument("-l", "--location", help="Location", required=True)
    parser.add_argument("-g", "--geo_key", help="GEO API Secret")
    args = parser.parse_args()

    # Check service
    if args.auth not in ['ptc', 'google']:
        logging.error('Invalid auth service {}'.format(args.auth))
        sys.exit(-1)
    '''
    # Create PokoAuthObject
    '''
    poko_session = PokeAuthSession(
        args.username,
        args.password,
        args.auth,
        geo_key=args.geo_key
    )
    '''
    poko_session = PokeAuthSession(
        'aznpwnzor',
        'M3ganfoxroxmysox?',
        'google'
    )

    # Authenticate with a given location
    # Location is not inherent in authentication
    # But is important to session
    #session = poko_session.authenticate(args.location)
    #session = poko_session.authenticate('San Francisco, CA')
    #session = poko_session.authenticate('480 Potrero Ave. San Francisco, CA')
    #session = poko_session.authenticate('250 King St. San Francisco, CA')
    #session = poko_session.authenticate('4th St. and Market St. San Francisco, CA')
    #session = poko_session.authenticate('735 Market St. San Francisco, CA')
    session = poko_session.authenticate('Union Square, San Francisco, CA')


    # Time to show off what we can do
    if session:

        # General
        getProfile(session)
        getInventory(session)

        # Pokemon related
        #pokemon = findClosestPokemon(session)
        #walkAndCatch(session, pokemon)

        # Pokestop related
        #fort = findClosestFort(session)
        #walkAndSpin(session, fort)

    else:
        logging.critical('Session not created successfully')
