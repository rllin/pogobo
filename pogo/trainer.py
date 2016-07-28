import argparse
import logging
import time
import heapq
import sys
import json
import numpy as np
import random
from collections import defaultdict

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
    formatter = logging.Formatter('Line %(lineno)d, %(filename)s - %(asctime)s - %(levelname)s - %(message)s')
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
        self.maintenance()
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

    def sort_pokemon(self, value=lambda x: valuator.perfect(x.individual_attack, x.individual_defense, x.individual_stamina)):
        party = self.inventory['party']
        pokes = defaultdict(list)
        for poke in party:
            pokes[poke.pokemon_id].append(poke)
        for id, indi_poke in pokes.items():
            if len(indi_poke) > 1:
                #indi_poke.sort(key=lambda x: valuator.perfect(x.individual_attack, x.individual_defense, x.individual_stamina))
                indi_poke.sort(key=value)
        return pokes

    def release_the_weak(self, num_keep=1):
        pokes = self.sort_pokemon()
        for id, indi_poke in pokes.items():
            if id == 133:
                num_to_keep = num_keep * 3
            else:
                num_to_keep = num_keep
            for poke in indi_poke[:-num_to_keep]:
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
            logging.info("Threw away %d %s" % (bag[item_id] - number_to_have, mappings.items_id[item_id]))
        self.status_update()

    def trim_all_items(self, number_to_have=10):
        priviledged_items = [mappings.items[item] for item in self.config['priviledged_items']]
        semi_priviledged_items = {mappings.items[item]: count for item, count in self.config['semi_priviledged_items'].items()}
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
            self.session.walk_to(self.lat + random.gauss(0, jitter), self.long + random.gauss(0, jitter))
            close_forts = self.sort_forts()
        return close_forts[1]


    def walk_to_fort(self):
        closest = self.find_closest_fort()
        logging.info('heading to Pokestop %s located at %f, %f' % (closest.id, closest.latitude, closest.longitude))
        self.session.walk_to(closest.latitude, closest.longitude, step_lambda=self.find_encounter_pokemon, step_lambda_kwargs={'radius': 30}, step_call=4)
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
                    break
        if not ball:
            if not alt:
                raise GeneralPogoException("Out of usable balls")
        else:
            ball = alt
        return ball

    def catch_pokemon(self, pokemon, thresh=0.1, max_attempt=3):
        attempt = 0
        bag = self.inventory['bag']
        encounter = self.session.encounter_pokemon(pokemon)
        chances = encounter.capture_probability.capture_probability
        balls = encounter.capture_probability.pokeball_type

        if encounter.status == 1:
            try:
                ball = self.choose_ball(chances, balls, bag, thresh)
            except GeneralPogoException as e:
                logging.info(e)
            catch_result = self.session.catch_pokemon(pokemon, ball)
            while catch_result.status not in [1, 3] and attempt < max_attempt:
                catch_result = self.session.catch_pokemon(pokemon, ball)
                attempt += 1
            self.status_update()
            return catch_result
        else:
            raise GeneralPogoException("Did not encounter")

    def find_encounter_pokemon(self, radius=20):
        logging.info('Finding nearby Pokemon')
        self.scan(radius=radius)
        for cell in self.cells.map_cells:
            #pokemons = [p for p in cell.wild_pokemons] + [p for p in cell.catchable_pokemons]
            pokemons = [p for p in cell.wild_pokemons]
            if len(pokemons) > 0:
                for pokemon in pokemons:
                    pokemon_id = getattr(pokemon, 'pokemon_id', None)
                    if not pokemon_id:
                        pokemon_id = pokemon.pokemon_data.pokemon_id
                    logging.info("Found %s at %f, %f" % (
                        mappings.id_name[pokemon_id],
                        pokemon.latitude,
                        pokemon.longitude
                    ))
                    try:
                        catch_result = self.catch_pokemon(pokemon)
                        logging.info('%s caught a %s' % ('Successfully' if catch_result.status == 1 else 'Unsuccessfully', mappings.id_name[pokemon_id]))
                    except GeneralPogoException as e:
                        logging.info(e)

    def walk_and_tour(self, target_stops, lure=True):
        stop = 0
        while stop < target_stops:
            closest, fort_response = self.walk_to_fort()
            if fort_response.result == 1:
                stop += 1
                logging.info('spun %d Pokestops so far' % stop)
            if lure:
                if hasattr(closest, 'lure_info'):
                    self.find_encounter_pokemon(radius=30)
            else:
                self.find_encounter_pokemon(radius=30)

            self.maintenance()
            stats = self.inventory['stats']
            prev_xp = mappings.level_xp_reach[stats.level - 1]
            next_xp = mappings.level_xp_reach[stats.level]
            logging.info('Level %d (%d/%d) %2.2f%% to Level %d' % (stats.level, stats.experience, next_xp, (stats.experience - prev_xp) / float(next_xp - prev_xp), stats.level + 1))
            time.sleep(self.pause)

    def set_egg(self, incub_id=901):
        if incub_id not in [901, 902]:
            raise GeneralPogoException('Select correct incubator id')
        eggs = filter(lambda x: x.egg_incubator_id == '', self.inventory['eggs'])
        incubators = filter(lambda x: x.start_km_walked == 0.0 and x.item_id == incub_id)
        if len(incubators) == 0:
            raise GeneralPogoException('No %s incubator available' % mappings.items_id[incub_id])
        if len(eggs) == 0:
            raise GeneralPogoException('No eggs available')
        egg = sorted(eggs, key=lambda x: x.egg_km_walked_target)[0]
        self.session.set_egg(incubator, egg)
        logging.info("Set %d km egg in incubator" % egg.egg_km_walked_target)

    def print_profile(self):
        self.status_update()
        player_data = self.profile.player_data
        s = 'Overview\n'
        s += 'Username: ' + player_data.username + '\n'
        s += '%s: %d' % (player_data.currencies[1].name, player_data.currencies[1].amount) + '\n'
        s += 'Level: ' + str(self.inventory['stats'].level) + '\n'
        s += 'Pokedex entries: ' + str(self.inventory['stats'].unique_pokedex_entries) + '\n'
        s += 'Best Pokemon: \n'
        candies = self.inventory['candies']
        for id, poke in sorted(self.sort_pokemon().items()):
            base_pokemon = mappings.families[id]['base_pokemon']
            candies_needed = mappings.families[id]['candy_to_evolve']
            s += '\t%s:\n\t\tcp: %d\n\t\tIVs: %d|%d|%d\n\t\tcandies: %d / %d\n' % (mappings.id_name[id], poke[-1].cp, poke[-1].individual_attack, poke[-1].individual_defense, poke[-1].individual_stamina, candies[base_pokemon] if base_pokemon in candies else 0, candies_needed if candies_needed else 0)
        return s

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--config_file")
    parser.add_argument("-n", "--number_stops")
    args = parser.parse_args()
    #t = Trainer('./config_personal.json')
    #t = Trainer('./config_miller_wench.json')
    t = Trainer(args.config_file)
    print t.print_profile()
    t.walk_and_tour(int(args.number_stops))




