import datetime
import logging
import random
from typing import Tuple

import numpy as np
import pandas as pd
from carball.generated.api.game_pb2 import Game
from tensorflow.python.keras.callbacks import ModelCheckpoint

from data.calculated_local_dm import CalculatedLocalDM
from data.calculatedgg_api.api_interfacer import CalculatedApiInterfacer
from data.calculatedgg_api.query_params import CalculatedApiQueryParams
from data.utils.columns import PlayerColumn, BallColumn, GameColumn
from data.utils.utils import filter_columns, flip_teams, normalise_df
from trainers.batch_trainer import BatchTrainer
from trainers.callbacks.metric_tracer import MetricTracer
from trainers.callbacks.metrics import ClassificationMetrics
from trainers.callbacks.prediction_plotter import PredictionPlotter
from trainers.callbacks.tensorboard import get_tensorboard
from trainers.sequences.calculated_sequence import CalculatedSequence
from x_things.x_goals_conv_model import XGoalsConvModel
from x_things.x_things_model import XThingsModel

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
logging.getLogger("carball").setLevel(logging.CRITICAL)
logging.getLogger("data.base_data_manager").setLevel(logging.WARNING)


def get_input_and_output_from_game_datas(df: pd.DataFrame, proto: Game) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    logger.debug('Getting input and output')

    df = normalise_df(df, inplace=True)
    name_team_map = {player.name: player.is_orange for player in proto.players}

    # Set up data
    INPUT_COLUMNS = [
        PlayerColumn.POS_X, PlayerColumn.POS_Y, PlayerColumn.POS_Z,
        PlayerColumn.ROT_X, PlayerColumn.ROT_Y, PlayerColumn.ROT_Z,
        PlayerColumn.VEL_X, PlayerColumn.VEL_Y, PlayerColumn.VEL_Z,
        # PlayerColumn.ANG_VEL_X, PlayerColumn.ANG_VEL_Y, PlayerColumn.ANG_VEL_Z,
        BallColumn.POS_X, BallColumn.POS_Y, BallColumn.POS_Z,
        BallColumn.VEL_X, BallColumn.VEL_Y, BallColumn.VEL_Z,
        GameColumn.SECONDS_REMAINING
    ]
    filtered_df = filter_columns(df, INPUT_COLUMNS).fillna(0).astype(float)
    filtered_df_orange = flip_teams(filtered_df)

    player_id_to_player = {
        player.id.id: player
        for player in proto.players
    }

    hits = proto.game_stats.hits
    inputs = []
    outputs = []
    for hit in hits:
        # if not hit.shot:
        #     continue
        player_name = player_id_to_player[hit.player_id.id].name

        player = [player for player in proto.players if player.name == player_name][0]

        # Make player taking shot be blue
        _df = filtered_df_orange if player.is_orange else filtered_df
        # Get right frame

        try:
            frame = _df.loc[hit.frame_number - random.randrange(10), :]
        except KeyError:
            frame = _df.loc[hit.frame_number, :]

        # Move player taking shot
        def key_fn(player_name: str) -> int:
            # Move player to front, move team to front.
            if player_name == player.name:
                return 0
            elif name_team_map[player_name] == player.is_orange:
                return 1
            else:
                return 2

        sorted_players = sorted(
            [player.name for player in proto.players],
            key=key_fn
        ) + ['ball', 'game']

        frame = frame.reindex(sorted_players, level=0)
        inputs.append(frame.values)
        hit_output = [bool(getattr(hit, category)) for category in HIT_CATEGORIES]
        outputs.append(hit_output)

    input_ = np.array(inputs, dtype=np.float32)
    output = np.array(outputs, dtype=np.float32)

    logger.debug(f'Got input and output: input shape: {input_.shape}, output shape:{output.shape}')
    assert not np.any(np.isnan(input_)), "input contains nan"
    assert not np.any(np.isnan(output)), "output contains nan"

    assert INPUT_FEATURES in input_.shape, f"input has shape {input_.shape}, expected: {INPUT_FEATURES}."

    return input_, output, get_sample_weight(output)


def get_sample_weight(output: np.ndarray):
    weights = np.ones_like(output)
    for output_category in (0, 1):
        category_mask = output == output_category
        if category_mask.any():
            weights[category_mask] = 1 / np.sum(category_mask)
    return weights.flatten()


INPUT_FEATURES = 61
# HIT_CATEGORIES = ['pass_', 'passed', 'dribble', 'dribble_continuation', 'shot', 'goal', 'assist', 'assisted',
#                   'save', 'aerial']
# HIT_CATEGORIES = ['pass_', 'shot', 'goal', 'aerial']
HIT_CATEGORIES = ['goal']
# HIT_CATEGORIES = ['shot']


if __name__ == '__main__':
    # filepath = r"x_goals.440-0.91998.hdf5"
    # model = XGoalsConvModel(INPUT_FEATURES, len(HIT_CATEGORIES), load_from_filepath=filepath)
    model = XGoalsConvModel(INPUT_FEATURES, len(HIT_CATEGORIES))

    interfacer = CalculatedApiInterfacer(
        CalculatedApiQueryParams(playlist=13, minmmr=1350, maxmmr=1550,
                                 start_timestamp=int(datetime.datetime(2018, 11, 1).timestamp()))
    )
    sequence = CalculatedSequence(
        interfacer=interfacer,
        game_data_transformer=get_input_and_output_from_game_datas,
    )

    EVAL_COUNT = 50
    eval_sequence = sequence.create_eval_sequence(EVAL_COUNT)
    eval_inputs, eval_outputs, _UNUSED_eval_weights = eval_sequence.as_arrays()

    save_callback = ModelCheckpoint('x_goals.{epoch:02d}-{val_acc:.5f}.hdf5', monitor='val_acc', save_best_only=True)
    classificaion_metrics = ClassificationMetrics((eval_inputs, eval_outputs))
    callbacks = [
        classificaion_metrics,
        MetricTracer(),
        save_callback,
        get_tensorboard(),
        # PredictionPlotter(),
    ]
    model.fit_generator(sequence,
                        steps_per_epoch=500,
                        validation_data=eval_sequence, epochs=1000, callbacks=callbacks,
                        workers=4, use_multiprocessing=True)
