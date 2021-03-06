import torch
import numpy as np
import torch.nn as nn

import datetime, time
import os

from kamarl.ppo import PPOAgent
from kamarl.utils import find_cuda_device, count_parameters
from kamarl.agents import IndependentAgents
from kamarl.logging import WandbLogger

from marlgrid.envs import env_from_config
# from marlgrid import envs as marl_envs
from marlgrid.agents import GridAgentInterface
from marlgrid.utils.video import GridRecorder


run_time = datetime.datetime.now().strftime("%m_%d_%H:%M:%S")
# device = find_cuda_device('1080 Ti')[1]
device = torch.device('cpu')

save_root = os.path.abspath(os.path.expanduser(f'/tmp/marlgrid_ppo_refactor/{run_time}'))

num_episodes = int(1e6)

# Config for a cluttered multigrid
env_config = {
    'env_class': 'ClutteredMultiGrid',

    'grid_size': 9,
    'max_steps': 150,
    'clutter_density': 0.2,
    'respawn': True,
    'ghost_mode': True,
    'reward_decay': False, # default true.
}

# Config for a cluttered goal cycle environment
env_config = {
    'env_class': 'ClutteredGoalCycleEnv',
    'grid_size': 13,
    'max_steps': 300,
    'clutter_density': 0.2,
    'respawn': True,
    'ghost_mode': True,
    'reward_decay': False, # default true.
    'n_bonus_tiles': 3,
    'initial_reward': True,
    'penalty': -0.5,
}

agent_interface_config = {
    'view_tile_size': 3,
    'view_size': 7,
    'view_offset': 3,
    'observation_style': 'rich',
    'prestige_beta': 0.95, # determines the rate at which prestige decays
    'color': 'prestige',
    'spawn_delay': 100,
}

ppo_learning_config = {
    "batch_size": 8,
    'num_minibatches': 10,
    "minibatch_size": 256,
    "minibatch_seq_len": 8,
    "hidden_update_interval": 10,

    'learning_rate': 1.e-4, # 1.e-3, #
    "kl_target":  0.01,
    "clamp_ratio": 0.2,
    "lambda":0.97,
    "gamma": 0.99,
    'entropy_bonus_coef': 0.0,#0001,
    'value_loss_coef': 1.0,
}

ppo_model_config = {
    "conv_layers" : [
        {'out_channels': 8, 'kernel_size': 3, 'stride': 3, 'padding': 0},
        {'out_channels': 16, 'kernel_size': 3, 'stride': 1, 'padding': 0},
        {'out_channels': 16, 'kernel_size': 3, 'stride': 1, 'padding': 0},
    ],
    'input_trunk_layers': [192],
    'lstm_hidden_size': 192,
    'val_mlp_layers': [64,64],
    'pi_mlp_layers': [64,64],
}

load_agents = [] # List of save paths of already-made agents to load into the env
n_new_agents = 1 # Number of new agents to be created with the above config/hyperparameters.


grid_agents = []
new_agents_info = [
    {'interface_config': agent_interface_config, 'learning_config': ppo_learning_config, 'model_config': ppo_model_config}
    for _ in range(n_new_agents)
]

grid_agents = []

for agent_load_path in load_agents:
    grid_agents.append(PPOAgent.load(agent_load_path))


for agent_info in new_agents_info:
    iface = GridAgentInterface(**agent_info['interface_config'])
    new_fella = PPOAgent(
        observation_space=iface.observation_space,
        action_space=iface.action_space, 
        learning_config=agent_info['learning_config'],
        model_config=agent_info['model_config'],
    )
    new_fella.metadata['marlgrid_interface'] = agent_interface_config
    grid_agents.append(new_fella)


agents = IndependentAgents(*grid_agents)

agents.set_device(device)
print(f"Agents have {count_parameters(agents.agents[0].ac)} parameters.")


env = env_from_config(env_config)
for agent in agents:
    env.add_agent(GridAgentInterface(**agent.metadata['marlgrid_interface']))
# env = marl_envs.ClutteredGoalCycleEnv([agent_interface.clone() for agent in agents], **env_config)


wbl = None
# wbl = WandbLogger(name='ppo', project='marlgrid_stale_refreshing_test')
# agents.set_logger(wbl)
# wbl.log_hyperparams({
#     'env_name': env.__class__.__name__,
#     'env_params': env_config,
#     'hparams': agents[0].hyperparams})

# env = GridRecorder(
#     env,
#     max_steps=env_config['max_steps']+1,
#     save_root=save_root,
#     auto_save_interval=100,
# )



total_reward = 0
total_steps = 0
for ep_num in range(num_episodes):
    # Initialize the environment and state
    obs_array = env.reset()
    done = False
    with agents.episode():
        with torch.set_grad_enabled(False):
            if ep_num >0 and ep_num % 1000==0:
                import pdb; pdb.set_trace()
            ep_start_time = time.time()

            ep_steps = 0
            ep_reward = 0
            # env.render(show_agent_views=True)
            agent_total_rewards = None
            while not done:
                # Get an action for each agent.
                # action_array = [agent.action_space.sample() for agent in agents]

                action_array = agents.action_step(obs_array)

                next_obs_array, reward_array, done_array, _ = env.step(action_array)

                total_reward += reward_array.sum()
                ep_reward += reward_array.sum()

                agents.save_step(obs_array, action_array, reward_array, done_array)

                obs_array = next_obs_array
                done = np.array(done_array).all()

                
                # print(ep_steps, tuple(action_array))
                # time.sleep(0.1)
                # env.render(show_agent_views=True)
                # input()

                ep_steps += 1
                total_steps += 1


            ep_time = time.time() - ep_start_time
            if ep_num % 500 == 0:
                agents[0].save(os.path.join(save_root, f"episode_{ep_num}/"))

            print(
                f"Episode {ep_num: >5d}: len={ep_steps: <4d} | cum rew={total_reward: <4.1f} ({ep_reward: >+3.1f}) | fps={ep_steps/ep_time: >5.2f}"
            )
                