import logging
import time
import heapq
import sys
import json
import numpy as np

from custom_exceptions import GeneralPogoException
from api import PokeAuthSession
from location import Location

from constants import mappings
from helpers import valuator

def setup_logger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('Line %(lineno)d,%(filename)s - %(asctime)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)


class Trainer:
    def __init__(self, config_file):
        with open(config_file) as f:
            self.config = json.load(f)

        self.pause = self.config['pause']

        setup_logger()
        self.auth()
        self.status_update()
        self.recent_forts = []

    def auth(self):
        self.poko_session = PokeAuthSession(
            self.config['username'],
            self.config['password'],
            self.config['auth']
        )
        self.session = self.poko_session.authenticate(self.config['starting_location'])
        return self.session

    def status_update(self):
        self.profile = self.session.get_profile()
        self.inventory = self.session.get_inventory()
        self.lat, self.long, _ = self.session.get_coordinates()

    def check_bag_full(self):
        return sum(self.inventory['bag'].values()) >= self.profile.player_data.max_item_storage - 10

    def check_party_full(self):
        return len(self.inventory['party']) >= self.profile.player_data.max_pokemon_storage - 10

    def maintenance(self):
        if self.check_bag_full():
            self.trim_all_items()
        if self.check_party_full():
            self.release_the_weak()

    def release_the_weak(self, num_keep=1):
        party = self.inventory['party']
        pokes = defaultdict(list)
        for poke in party:
            pokes[poke.pokemon_id].append(poke)
        for id, indi_poke in pokes.items():
            if len(indi_poke) > 1:
                indi_poke.sort(key=lambda x: valuator.perfect(x.individual_attack, x.individual_defense, x.individual_stamina))
                for poke in indi_poke[:-num_keep]:
                    self.session.release_pokemon(poke)
                    logging.info('Releasing %s (%d|%d|%d)' % (mappings.id_name[poke.pokemon_id], poke.individual_attack, poke.individual_defense, poke.individual_stamina))
                    time.sleep(self.pause)
        self.status_update()


    def trim_items(self, item, number_to_have):
        bag = self.inventory['bag']
        if type(item) is not int:
            item_id = mappings.items[item]
        else:
            item_id = item
        if bag[item_id] > number_to_have:
            self.session.recycle_item(item_id, bag[item_id] - number_to_have)
            logging.info("Threw away %d %d" % (bag[item_id] - number_to_have, item_id))
        self.status_update()

    def trim_all_items(self, number_to_have=10):
        priviledged_items = [mappings.items[item] for item in self.config['priviledged_items']]
        semi_priviledged_items = {mappings.items[item]: count for item, count in self.config['semi_priviledged_items'].items()}
        print priviledged_items
        print semi_priviledged_items
        bag = self.inventory['bag']
        for item_id, count in bag.items():
            if item_id in semi_priviledged_items.keys():
                self.trim_items(item_id, semi_priviledged_items[item_id])
            elif item_id not in priviledged_items:
                self.trim_items(item_id, number_to_have)

    def scan(self, radius):
        self.cells = self.session.get_map_objects(radius=radius)

    def sort_forts(self):
        ordered_forts = []
        for cell in self.cells.map_cells:
            for fort in cell.forts:
                dist = Location.getDistance(
                    self.lat, self.long,
                    fort.latitude, fort.longitude
                )
                if fort.type == 1:
                    ordered_forts.append({'distance': dist, 'fort': fort})
        ordered_forts = sorted(ordered_forts, key=lambda k: k['distance'])
        result = [instance['fort'] for instance in ordered_forts if instance['fort'].id not in [fort.id for fort in self.recent_forts]]
        return result

    def find_closest_fort(self, radius=20, jitter=0.02):
        self.scan(radius=radius)
        logging.info("Finding nearest Pokestops")
        close_forts = self.sort_forts()
        while len(close_forts) == 0:
            self.session.walk_to(self.lat + random.normal(0, jitter), self.long + random.normal(0, jitter))
            close_forts = self.sort_forts(radius=radius)
        return close_forts[1]


    def walk_to_fort(self):
        closest = self.find_closest_fort()
        logging.info('heading to Pokestop %s located at %f, %f' % (closest.id, closest.latitude, closest.longitude))
        self.session.walk_to(closest.latitude, closest.longitude)
        fort_response = self.session.get_fort_search(closest)
        if fort_response.result == 1:
            logging.info("Pokestop spun succesfully")
            if len(self.recent_forts) > 0 and self.recent_forts[0].cooldown_complete_timestamp_ms < time.time() * 1000:
                self.recent_forts.pop(0)
        if closest not in self.recent_forts:
            self.recent_forts.append(closest)
        self.status_update()
        return closest, fort_response

    def choose_ball(self, chances, balls, bag, thresh):
        alt, best = None, None
        for ball, chance in zip(balls, chances):
            if ball in bag and bag[ball] > 0:
                alt = ball
                if chance > thresh:
                    best = ball
        return best
        '''
                    break
        if not alt:
            raise GeneralPogoException("Out of usable balls")
        else:
            return best
        '''

    def catch_pokemon(self, pokemon, thresh=0.1, max_attempt=3):
        attempt = 0
        bag = self.inventory['bag']
        encounter = self.session.encounter_pokemon(pokemon)
        chances = encounter.capture_probability.capture_probability
        balls = encounter.capture_probability.pokeball_type

        ball = self.choose_ball(chances, balls, bag, thresh)
        if encounter.status:
            balls[chances > thresh]
            catch_result = self.session.catch_pokemon(pokemon, ball)
            while catch_result.status not in [1, 3] and attempt < max_attempt:
                catch_result = self.session.catch_pokemon(pokemon, ball)
                attempt += 1
            self.status_update()
            return catch_result

    def find_encounter_pokemon(self):
        logging.info('Finding nearby Pokemon')
        self.scan(radius=20)
        for cell in self.cells.map_cells:
            #pokemons = [p for p in cell.wild_pokemons] + [p for p in cell.catchable_pokemon]
            pokemons = [p for p in cell.wild_pokemons]
            if len(pokemons) > 0:
                for pokemon in pokemons:
                    logging.info("Found %s at %f, %f" % (
                        mappings.id_name[pokemon.pokemon_data.pokemon_id],
                        pokemon.latitude,
                        pokemon.longitude
                    ))
                    catch_result = self.catch_pokemon(pokemon)
                    logging.info('%s caught a %s' % ('Successfully' if catch_result.status == 1 else 'Unsuccessfully', mappings.id_name[pokemon.pokemon_data.pokemon_id]))

    def walk_and_tour(self, target_stops):
        stop = 0
        while stop < target_stops:
            if stop % 10:
                self.maintenance()
            closest, fort_response = self.walk_to_fort()
            if fort_response.result:
                stop += 1
                logging.info('spun %d Pokestops so far' % stop)
            if hasattr(closest, 'lure_info'):
                self.find_encounter_pokemon()
            stats = self.inventory['stats']
            logging.info('Level %d (%d/%d) %2.2f%% to Level %d' % (stats.level, stats.experience, stats.next_level_xp, (stats.experience - stats.prev_level_xp) / float(stats.next_level_xp - stats.prev_level_xp) * 100.0, stats.level + 1))
            time.sleep(self.pause)

if __name__ == '__main__':
    t = Trainer('./config.json')
    t.walk_and_tour(100)




