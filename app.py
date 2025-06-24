#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os, sys
import click
import re

from flask import Flask
from flask import request
from flask import jsonify

import docker

app = Flask(__name__)
client = docker.from_env()

@app.route('/')
def main():
    return jsonify(success=True), 200

@app.route('/images/pull', methods=['POST'])
def image_puller():
    # 1. Validate required parameters: token, repository, and optionally tag
    if not request.form.get('token') or not request.form.get('repository'):
        return jsonify(success=False, error="Missing parameters 'token' or 'repository'"), 400

    image_repo = request.form['repository']
    image_tag = request.form.get('tag', 'latest')
    full_image_name_for_pull = f"{image_repo}:{image_tag}"
    
    if request.form['token'] != os.environ.get('TOKEN', ''):
        return jsonify(success=False, error="Invalid token"), 403

    restart_containers = request.form.get('restart_containers', 'false').lower() == "true"

    # 2. Pull the new image
    print(f"Pulling new image: {full_image_name_for_pull}...")
    try:
        client.images.pull(image_repo, tag=image_tag)
        print(f"Successfully pulled {full_image_name_for_pull}")
    except docker.errors.ImageNotFound:
        print(f"Error: Image '{full_image_name_for_pull}' not found in registry.")
        return jsonify(success=False, error=f"Image '{full_image_name_for_pull}' not found."), 404
    except docker.errors.APIError as e:
        print(f"Error pulling image {full_image_name_for_pull}: {e}")
        return jsonify(success=False, error=f"Failed to pull image {full_image_name_for_pull}: {e}"), 500
    except Exception as e:
        print(f"An unexpected error occurred while pulling image: {e}")
        return jsonify(success=False, error=f"An unexpected error occurred while pulling image: {e}"), 500
    
    if not restart_containers:
        print(f"Option 'restart_containers' is false. Image pulled, but no containers will be restarted.")
        return jsonify(success=True, message=f"Image {full_image_name_for_pull} pulled successfully. No containers restarted as requested."), 200

    # 3. Identify containers to update
    old_containers_to_update = []
    print(f"Scanning for running containers based on image '{full_image_name_for_pull}'...")
    try:
        for container in client.containers.list():
            # A container's image can have multiple tags, so we check if our target is among them
            #if re.match( r'.*' + re.escape(image) + r'$', container.attrs['Config']['Image']):
            if full_image_name_for_pull in container.image.tags:
                old_containers_to_update.append(container)
                print(f" - Found container to update: {container.name} (ID: {container.id[:12]})")

            # Also consider containers that might just use the repository name without a specific tag, especially if the pulled image is 'latest'
            elif image_tag == 'latest' and image_repo in container.image.tags:
                old_containers_to_update.append(container)
                print(f" - Found container to update (implicit latest): {container.name} (ID: {container.id[:12]})")

    except docker.errors.APIError as e:
        print(f"Error listing containers: {e}")
        return jsonify(success=False, error=f"Failed to list containers: {e}"), 500

    if not old_containers_to_update:
        print(f"No running containers found using image '{full_image_name_for_pull}'. Nothing to update.")
        return jsonify(success=True, message=f"No containers to update for image {full_image_name_for_pull}."), 200

    print(f"Found {len(old_containers_to_update)} container(s) to update.")

    # 4. Process each container individually
    updated_count = 0
    failed_count = 0

    for old_container in old_containers_to_update:
        original_container_name = old_container.name
        old_container_id = old_container.id[:12]
        print(f"\n--- Processing container: {original_container_name} (ID: {old_container_id}) ---")

        try:
            # 4.1: Get configuration from old container
            config = old_container.attrs['Config']
            host_config_attrs = old_container.attrs['HostConfig']
            network_settings = old_container.attrs['NetworkSettings']
            
            # 4.2: Stop old container
            print(f"Stopping old container '{original_container_name}' (ID: {old_container_id})...")
            old_container.stop(timeout=30) # Give it 30 seconds to stop gracefully
            print(f"Old container stopped.")

            # 4.3: Remove old container
            print(f"Removing old container '{original_container_name}' (ID: {old_container_id})...")
            old_container.remove()
            print(f"Old container removed.")

            # 4.4 Prepare arguments for create_container
            create_args = {
                'image': config.get('Image'), # This will be the image name/tag, e.g., "my_app:latest"
                                              # Docker will use the *newly pulled* version.
                'name': original_container_name, # Use the original name for the new container
                'environment': config.get('Env'),
                'labels': config.get('Labels'),
                'command': config.get('Cmd'),
                'entrypoint': config.get('Entrypoint'),
                'working_dir': config.get('WorkingDir'),
                'hostname': config.get('Hostname'),
                'user': config.get('User'),
                'tty': config.get('Tty', False), # Default to False if not present
                'stdin_open': config.get('OpenStdin', False), # Default to False if not present
                'attach_stdin': config.get('AttachStdin', False),
                'attach_stdout': config.get('AttachStdout', True),
                'attach_stderr': config.get('AttachStderr', True),
                'stop_signal': config.get('StopSignal'),
                'stop_timeout': config.get('StopTimeout'),
                'healthcheck': config.get('Healthcheck'),
                'volumes': config.get('Volumes'), # Anonymous volumes
                'read_only': config.get('ReadonlyRootfs', False),
            }

            # Prepare host config
            # Use client.api.create_host_config to correctly format host-specific options
            host_config = client.api.create_host_config(
                binds=host_config_attrs.get('Binds'),
                port_bindings=host_config_attrs.get('PortBindings'),
                links=host_config_attrs.get('Links'),
                lxc_conf=host_config_attrs.get('LxcConf'),
                privileged=host_config_attrs.get('Privileged', False),
                publish_all_ports=host_config_attrs.get('PublishAllPorts', False),
                dns=host_config_attrs.get('Dns'),
                dns_search=host_config_attrs.get('DnsSearch'),
                extra_hosts=host_config_attrs.get('ExtraHosts'),
                volumes_from=host_config_attrs.get('VolumesFrom'),
                cap_add=host_config_attrs.get('CapAdd'),
                cap_drop=host_config_attrs.get('CapDrop'),
                group_add=host_config_attrs.get('GroupAdd'),
                devices=host_config_attrs.get('Devices'),
                log_config=host_config_attrs.get('LogConfig'),
                #memory=host_config_attrs.get('Memory'),
                #memory_swap=host_config_attrs.get('MemorySwap'),
                #memory_reservation=host_config_attrs.get('MemoryReservation'),
                #kernel_memory=host_config_attrs.get('KernelMemory'),
                #cpu_period=host_config_attrs.get('CpuPeriod'),
                #cpu_quota=host_config_attrs.get('CpuQuota'),
                #cpu_shares=host_config_attrs.get('CpuShares'),
                #cpuset_cpus=host_config_attrs.get('CpusetCpus'),
                #cpuset_mems=host_config_attrs.get('CpusetMems'),
                #blkio_weight=host_config_attrs.get('BlkioWeight'),
                #blkio_device_read_bps=host_config_attrs.get('BlkioDeviceReadBps'),
                #blkio_device_write_bps=host_config_attrs.get('BlkioDeviceWriteBps'),
                #blkio_device_read_iops=host_config_attrs.get('BlkioDeviceReadIops'),
                #blkio_device_write_iops=host_config_attrs.get('BlkioDeviceWriteIops'),
                device_requests=host_config_attrs.get('DeviceRequests'), # For GPUs etc.
                pids_limit=host_config_attrs.get('PidsLimit'),
                ulimits=host_config_attrs.get('Ulimits'),
                auto_remove=host_config_attrs.get('AutoRemove', False),
                volume_driver=host_config_attrs.get('VolumeDriver'),
                shm_size=host_config_attrs.get('ShmSize'),
                sysctls=host_config_attrs.get('Sysctls'),
                runtime=host_config_attrs.get('Runtime'),
                cgroup_parent=host_config_attrs.get('CgroupParent'),
                oom_kill_disable=host_config_attrs.get('OomKillDisable', False),
                init=host_config_attrs.get('Init', False),
                # Note: NetworkMode is typically handled here if it's a single network
                network_mode=host_config_attrs.get('NetworkMode'),
                restart_policy=host_config_attrs.get('RestartPolicy'),
                # Add other host_config attributes as needed based on your usage
            )
            create_args['host_config'] = host_config

            # 4.5: Create new container with the original name
            print(f"Creating new container '{original_container_name}'...")
            new_container_response = client.api.create_container(**create_args)
            new_container = client.containers.get(new_container_response['Id'])
            print(f"New container '{new_container.name}' (ID: {new_container.id[:12]}) created.")

            # 4.6: Handle network connections (especially for multiple custom networks)
            # The 'NetworkMode' in HostConfig handles single network connections (e.g., bridge, host, custom_network_name).
            # For containers connected to multiple custom networks, we need to explicitly connect.
            if network_settings and network_settings.get('Networks'):
                for net_name, net_info in network_settings['Networks'].items():
                    # Skip the network if it's already set by HostConfig.NetworkMode (e.g., default bridge)
                    if host_config_attrs.get('NetworkMode') == net_name:
                        continue
                    try:
                        network = client.networks.get(net_name)
                        # Connect new container to this network, preserving IP if static
                        connect_kwargs = {}
                        if 'IPAddress' in net_info and net_info['IPAddress']:
                            connect_kwargs['ipv4_address'] = net_info['IPAddress']
                        if 'GlobalIPv6Address' in net_info and net_info['GlobalIPv6Address']:
                            connect_kwargs['ipv6_address'] = net_info['GlobalIPv6Address']
                        if 'Aliases' in net_info and net_info['Aliases']:
                            connect_kwargs['aliases'] = net_info['Aliases']
                        if 'Links' in net_info and net_info['Links']:
                             # Docker links are deprecated, but if present, pass them
                            connect_kwargs['links'] = net_info['Links']

                        print(f"Connecting new container to network '{net_name}' with {connect_kwargs or 'default settings'}...")
                        network.connect(new_container, **connect_kwargs)
                        print(f"New container connected to network '{net_name}'.")
                    except docker.errors.NotFound:
                        print(f"Warning: Network '{net_name}' not found. Skipping connection for this network.")
                    except docker.errors.APIError as net_err:
                        print(f"Warning: Failed to connect new container to network '{net_name}': {net_err}")

            # 4.7: Start new container
            print(f"Starting new container '{original_container_name}' (ID: {new_container.id[:12]})...")
            new_container.start()
            print(f"New container started.")

            updated_count += 1
            print(f"--- Successfully updated container '{original_container_name}' ---")

        except docker.errors.NotFound as e:
            print(f"Error: Container or resource not found during update for {original_container_name}: {e}")
            failed_count += 1
        except docker.errors.APIError as e:
            print(f"Error during Docker API call for {original_container_name}: {e}")
            failed_count += 1
        except Exception as e:
            print(f"An unexpected error occurred while processing container {original_container_name}: {e}")
            failed_count += 1

    final_status_message = (
        f"Update process finished. Successfully updated {updated_count} container(s), "
        f"failed to update {failed_count} container(s)."
    )
    print(f"\n{final_status_message}")

    if failed_count == 0:
        return jsonify(success=True, message=final_status_message), 200
    elif updated_count > 0:
        return jsonify(success=False, message=final_status_message, error="Partial success, some containers failed."), 207 # Multi-Status
    else:
        return jsonify(success=False, message=final_status_message, error="All container updates failed."), 500




@click.command()
@click.option('-h',      default='0.0.0.0', help='Set the host')
@click.option('-p',      default=8080,      help='Set the listening port')
@click.option('--debug', default=False,     help='Enable debug option')
def main(h, p, debug):
    if not os.environ.get('TOKEN'):
        print ('ERROR: Missing TOKEN env variable')
        sys.exit(1)

    registry_user = os.environ.get('REGISTRY_USERNAME')
    registry_passwd = os.environ.get('REGISTRY_PASSWORD')
    registry_url = os.environ.get('REGISTRY_URL', 'https://index.docker.io/v1/')

    if registry_user and registry_passwd:
        try:
            client.login(username=registry_user, password=registry_passwd, registry=registry_url)
        except Exception as e:
            print(e)
            sys.exit(1)

    app.run(
        host  = os.environ.get('HOST', default=h),
        port  = os.environ.get('PORT', default=p),
        debug = os.environ.get('DEBUG', default=debug)
    )

if __name__ == "__main__":
    main()
