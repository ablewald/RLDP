import requests
import json
import os
import csv

from data.calculatedgg_api.api_interfacer import CalculatedApiInterfacer
from constants import columns


class ReplayScraper:
    BASE_URL = 'https://calculated.gg/api/'

    def get_replay_meta(self, replay_id):
        response = requests.get(self.BASE_URL + 'replay/' + replay_id)
        return json.loads(response.text)

    def get_basic_player_stats(self, replay_id):
        response = requests.get(self.BASE_URL + 'replay/' + replay_id + '/basic_player_stats')
        return json.loads(response.text)

    def get_replay_data(self, replay_id):
        rp_meta = self.get_replay_meta(replay_id)
        player_stats = self.get_basic_player_stats(replay_id)
        rp_meta['player_stats'] = player_stats
        return self.format_data(rp_meta)

    def format_data(self, r):
        players = r['players']
        player_data = {}
        winner = self.winning_team(r['gameScore'])

        for player in players:
            player_data[player['name']] = {'name': player['name']}
            player_data[player['name']]['isOrange'] = player['isOrange']
            player_data[player['name']]['won'] = self.player_team(player['isOrange']) == winner
            player_data[player['name']]['game_id'] = r['id']
            player_data[player['name']]['game_type'] = r['gameMode']
        for stat in r['player_stats']:
            for player_stat in stat['chartDataPoints']:
                player_data[player_stat['name']][stat['title']] = player_stat['value']

        return [player_data[i] for i in player_data]

    @staticmethod
    def winning_team(game_score):
        if game_score['team0Score'] > game_score['team1Score']:
            return 'Blue'
        else:
            return 'Orange'

    @staticmethod
    def player_team(is_orange):
        if is_orange:
            return 'Orange'
        else:
            return 'Blue'


if __name__ == '__main__':
    cai = CalculatedApiInterfacer()
    replay_list = cai.get_all_replay_ids(limit=10)
    rs = ReplayScraper()

    with open(os.getcwd() + '/test.csv', 'w') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for replay_id in replay_list:
            replay_data = rs.get_replay_data(replay_id)
            for player_data in replay_data:
                writer.writerow(player_data)
