import datetime
import os
import sys

import gym
import numpy
import torch

from .abstract_game import AbstractGame

sys.path.append("ext/ManiSkill")
import mani_skill.env
#from mani_skill.utils.ee import EndEffectorInterface

ACTION_SPACE = list(range(13 * 2)) # 13 joints, 2 options (+/-) or each.
ACTION_PITCH = 0.1
HISTORY = 16
MAX_MOVES = 1000

class MuZeroConfig:
    def __init__(self):
        # More information is available here: https://github.com/werner-duvaud/muzero-general/wiki/Hyperparameter-Optimization

        self.seed = 0  # Seed for numpy, torch and the game
        self.max_num_gpus = None  # Fix the maximum number of GPUs to use. It's usually faster to use a single GPU (set it to 1) if it has enough memory. None will use every GPUs available

        ### Game
        self.observation_shape = (
            9,
            160,
            400,
        )  # Dimensions of the game observation, must be 3D (channel, height, width). For a 1D array, please reshape it to (1, 1, length of array)
        self.action_space = ACTION_SPACE  # Fixed list of all possible actions. You should only edit the length
        self.players = list(
            range(1)
        )  # List of players. You should only edit the length
        self.stacked_observations = HISTORY  # Number of previous observations and previous actions to add to the current observation

        # Evaluate
        self.muzero_player = 0  # Turn Muzero begins to play (0: MuZero plays first, 1: MuZero plays second)
        self.opponent = None  # Hard coded agent that MuZero faces to assess his progress in multiplayer games. It doesn't influence training. None, "random" or "expert" if implemented in the Game class

        ### Self-Play
        self.num_workers = 3  # Number of simultaneous threads/workers self-playing to feed the replay buffer
        self.selfplay_on_gpu = False
        self.max_moves = MAX_MOVES  # Maximum number of moves if game is not finished before
        self.num_simulations = 20  # Number of future moves self-simulated
        self.discount = 0.997  # Chronological discount of the reward
        self.temperature_threshold = None  # Number of moves before dropping the temperature given by visit_softmax_temperature_fn to 0 (ie selecting the best action). If None, visit_softmax_temperature_fn is used every time

        # Root prior exploration noise
        self.root_dirichlet_alpha = 0.25
        self.root_exploration_fraction = 0.25

        # UCB formula
        self.pb_c_base = 19652
        self.pb_c_init = 1.25

        ### Network
        self.network = "resnet"  # "resnet" / "fullyconnected"
        self.support_size = 10  # Value and reward are scaled (with almost sqrt) and encoded on a vector with a range of -support_size to support_size. Choose it so that support_size <= sqrt(max(abs(discounted reward)))

        # Residual Network
        self.downsample = "resnet"  # Downsample observations before representation network, False / "CNN" (lighter) / "resnet" (See paper appendix Network Architecture)
        self.blocks = 16  # Number of blocks in the ResNet
        self.channels = 2  # Number of channels in the ResNet
        self.reduced_channels_reward = 2  # Number of channels in reward head
        self.reduced_channels_value = 2  # Number of channels in value head
        self.reduced_channels_policy = 2  # Number of channels in policy head
        self.resnet_fc_reward_layers = (
            []
        )  # Define the hidden layers in the reward head of the dynamic network
        self.resnet_fc_value_layers = (
            []
        )  # Define the hidden layers in the value head of the prediction network
        self.resnet_fc_policy_layers = (
            []
        )  # Define the hidden layers in the policy head of the prediction network

        # Fully Connected Network
        self.encoding_size = 8
        self.fc_representation_layers = (
            []
        )  # Define the hidden layers in the representation network
        self.fc_dynamics_layers = [
            16
        ]  # Define the hidden layers in the dynamics network
        self.fc_reward_layers = [16]  # Define the hidden layers in the reward network
        self.fc_value_layers = [16]  # Define the hidden layers in the value network
        self.fc_policy_layers = [16]  # Define the hidden layers in the policy network

        ### Training
        self.results_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "../results",
            os.path.basename(__file__)[:-3],
            datetime.datetime.now().strftime("%Y-%m-%d--%H-%M-%S"),
        )  # Path to store the model weights and TensorBoard logs
        self.save_model = (
            True  # Save the checkpoint in results_path as model.checkpoint
        )
        self.training_steps = 1000000  # Total number of training steps (ie weights update according to a batch)
        self.batch_size = (
            64  # Number of parts of games to train on at each training step
        )
        self.checkpoint_interval = (
            30  # Number of training steps before using the model for self-playing
        )
        self.value_loss_weight = 1  # Scale the value loss to avoid overfitting of the value function, paper recommends 0.25 (See paper appendix Reanalyze)
        self.train_on_gpu = torch.cuda.is_available()  # Train on GPU if available

        self.optimizer = "Adam"  # "Adam" or "SGD". Paper uses SGD
        self.weight_decay = 1e-4  # L2 weights regularization
        self.momentum = 0.9  # Used only if optimizer is SGD

        # Exponential learning rate schedule
        self.lr_init = 0.02  # Initial learning rate
        self.lr_decay_rate = 0.9  # Set it to 1 to use a constant learning rate
        self.lr_decay_steps = 1000

        ### Replay Buffer
        self.replay_buffer_size = (
            100  # Number of self-play games to keep in the replay buffer
        )
        self.num_unroll_steps = (
            5  # Number of game moves to keep for every batch element
        )
        self.td_steps = 30  # Number of steps in the future to take into account for calculating the target value
        self.PER = False  # Prioritized Replay (See paper appendix Training), select in priority the elements in the replay buffer which are unexpected for the network
        self.PER_alpha = 0.5  # How much prioritization is used, 0 corresponding to the uniform case, paper suggests 1

        # Reanalyze (See paper appendix Reanalyse)
        self.use_last_model_value = True  # Use the last model to provide a fresher, stable n-step value (See paper appendix Reanalyze)
        self.reanalyse_on_gpu = False

        ### Adjust the self play / training ratio to avoid over/underfitting
        self.self_play_delay = 0  # Number of seconds to wait after each played game
        self.training_delay = 0  # Number of seconds to wait after each training step
        self.ratio = 1.5  # Desired training steps per self played step ratio. Equivalent to a synchronous version, training can take much longer. Set it to None to disable it

    def visit_softmax_temperature_fn(self, trained_steps):
        """
        Parameter to alter the visit count distribution to ensure that the action selection becomes greedier as training progresses.
        The smaller it is, the more likely the best action (ie with the highest visit count) is chosen.

        Returns:
            Positive float.
        """
        if trained_steps < 0.5 * self.training_steps:
            return 1.0
        elif trained_steps < 0.75 * self.training_steps:
            return 0.5
        else:
            return 0.25


class Game(AbstractGame):
    def __init__(self, seed=None):
        env_name = 'OpenCabinetDoor-v0'
        self.env = gym.make(env_name)
        self.env.set_env_mode(obs_mode='rgbd', reward_type='dense')
        self.history = numpy.zeros((9, 160, 400))
        #self.ee_interface = EndEffectorInterface(env_name)
        # Format: https://github.com/haosulab/ManiSkill/wiki/Detailed-Explanation-of-Action
        if seed is not None:
            self.env.seed(seed)
        #self.action_names = {
        #        0: "x velocity of moving platform",
        #        1: "y velocity of moving platform",
        #        2: "rotation velocity of moving platform",
        #        3: "height change velocity of robot body",
        #        4: "panda joint angle 1",
        #        5: "panda joint angle 2",
        #        6: "panda joint angle 3",
        #        7: "panda joint angle 4",
        #        8: "panda joint angle 5",
        #        9: "panda joint angle 6",
        #        10: "panda joint finger 1",
        #        11: "panda joint finger 2",
        #        }

    def step(self, action):
        action = self._mz2ms(action)
        observation, reward, done, _ = self.env.step(action)
        observation = observation["rgbd"]["rgb"].reshape((9, 160, 400))
        return observation, reward, done

    def legal_actions(self):
        return ACTION_SPACE

    def _mz2ms(self, action):
        joint = action // 2
        op = action // 13
        base = numpy.zeros((13,), dtype=float)
        base[joint] = [-1.0, 1.0][op] * ACTION_PITCH
        return base

    def reset(self):
        return self.env.reset()["rgbd"]["rgb"].reshape((9, 160, 400))

    def close(self):
        self.env.close()

    def render(self):
        self.env.render()
        input("Press enter to take a step ")

    #def action_to_string(self, action_number):
    #    return f"{action_number}. {self.action_names[action_number]}"
