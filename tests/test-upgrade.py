import os
import platform
import time
from validators import (
    validate_dns_dashboard,
    validate_storage,
    validate_ingress,
    validate_gpu,
    validate_registry,
    validate_forward,
    validate_metrics_server,
    validate_fluentd,
    validate_jaeger,
    validate_metallb_config,
)
from subprocess import check_call, CalledProcessError
from utils import (
    microk8s_enable,
    wait_for_pod_state,
    wait_for_installation,
    run_until_success,
    is_container,
)

upgrade_from = os.environ.get("UPGRADE_MICROK8S_FROM", "beta")
# Have UPGRADE_MICROK8S_TO point to a file to upgrade to that file
upgrade_to = os.environ.get("UPGRADE_MICROK8S_TO", "edge")
under_time_pressure = os.environ.get("UNDER_TIME_PRESSURE", "False")


class TestUpgrade(object):
    """
    Validates a microk8s upgrade path
    """

    def test_upgrade(self):
        """
        Deploy, probe, upgrade, validate nothing broke.

        """
        print("Testing upgrade from {} to {}".format(upgrade_from, upgrade_to))

        cmd = "sudo snap install microk8s --classic --channel={}".format(upgrade_from)
        run_until_success(cmd)
        wait_for_installation()
        if is_container():
            # In some setups (eg LXC on GCE) the hashsize nf_conntrack file under
            # sys is marked as rw but any update on it is failing causing kube-proxy
            # to fail.
            here = os.path.dirname(os.path.abspath(__file__))
            apply_patch = os.path.join(here, "patch-kube-proxy.sh")
            check_call("sudo {}".format(apply_patch).split())

        # Run through the validators and
        # select those that were valid for the original snap
        test_matrix = {}
        try:
            enable = microk8s_enable("dns")
            wait_for_pod_state("", "kube-system", "running", label="k8s-app=kube-dns")
            assert "Nothing to do for" not in enable
            enable = microk8s_enable("dashboard")
            assert "Nothing to do for" not in enable
            validate_dns_dashboard()
            test_matrix["dns_dashboard"] = validate_dns_dashboard
        except CalledProcessError:
            print("Will not test dns-dashboard")

        try:
            enable = microk8s_enable("storage")
            assert "Nothing to do for" not in enable
            validate_storage()
            test_matrix["storage"] = validate_storage
        except CalledProcessError:
            print("Will not test storage")

        try:
            enable = microk8s_enable("ingress")
            assert "Nothing to do for" not in enable
            validate_ingress()
            test_matrix["ingress"] = validate_ingress
        except CalledProcessError:
            print("Will not test ingress")

        try:
            enable = microk8s_enable("gpu")
            assert "Nothing to do for" not in enable
            validate_gpu()
            test_matrix["gpu"] = validate_gpu
        except CalledProcessError:
            print("Will not test gpu")

        try:
            enable = microk8s_enable("registry")
            assert "Nothing to do for" not in enable
            validate_registry()
            test_matrix["registry"] = validate_registry
        except CalledProcessError:
            print("Will not test registry")

        try:
            validate_forward()
            test_matrix["forward"] = validate_forward
        except CalledProcessError:
            print("Will not test port forward")

        try:
            enable = microk8s_enable("metrics-server")
            assert "Nothing to do for" not in enable
            validate_metrics_server()
            test_matrix["metrics_server"] = validate_metrics_server
        except CalledProcessError:
            print("Will not test the metrics server")

        # AMD64 only tests
        if platform.machine() == "x86_64" and under_time_pressure == "False":
            """
            # Prometheus operator on our lxc is chashlooping disabling the test for now.
            try:
                enable = microk8s_enable("prometheus", timeout_insec=30)
                assert "Nothing to do for" not in enable
                validate_prometheus()
                test_matrix['prometheus'] = validate_prometheus
            except:
                print('Will not test the prometheus')

            # The kubeflow deployment is huge. It will not fit comfortably
            # with the rest of the addons on the same machine during an upgrade
            # we will need to find another way to test it.
            try:
                enable = microk8s_enable("kubeflow", timeout_insec=30)
                assert "Nothing to do for" not in enable
                validate_kubeflow()
                test_matrix['kubeflow'] = validate_kubeflow
            except:
                print('Will not test kubeflow')
            """

            try:
                enable = microk8s_enable("fluentd", timeout_insec=30)
                assert "Nothing to do for" not in enable
                validate_fluentd()
                test_matrix["fluentd"] = validate_fluentd
            except CalledProcessError:
                print("Will not test the fluentd")

            try:
                enable = microk8s_enable("jaeger", timeout_insec=30)
                assert "Nothing to do for" not in enable
                validate_jaeger()
                test_matrix["jaeger"] = validate_jaeger
            except CalledProcessError:
                print("Will not test the jaeger addon")

            # We are not testing cilium because we want to test the upgrade of the default CNI
            """
            try:
                enable = microk8s_enable("cilium", timeout_insec=300)
                assert "Nothing to do for" not in enable
                validate_cilium()
                test_matrix['cilium'] = validate_cilium
            except CalledProcessError:
                print('Will not test the cilium addon')
            """
            try:
                ip_ranges = (
                    "192.168.0.105-192.168.0.105,192.168.0.110-192.168.0.111,192.168.1.240/28"
                )
                enable = microk8s_enable("{}:{}".format("metallb", ip_ranges), timeout_insec=500)
                assert "MetalLB is enabled" in enable and "Nothing to do for" not in enable
                validate_metallb_config(ip_ranges)
                test_matrix["metallb"] = validate_metallb_config
            except CalledProcessError:
                print("Will not test the metallb addon")

            # We will not be testing multus because it takes too long for cilium and multus
            # to settle after the update and the multus test needs to be refactored so we do
            # delete and recreate the networks configured.
            """
            try:
                enable = microk8s_enable("multus", timeout_insec=150)
                assert "Nothing to do for" not in enable
                validate_multus()
                test_matrix['multus'] = validate_multus
            except CalledProcessError:
                print('Will not test the multus addon')
            """

        # Refresh the snap to the target
        if upgrade_to.endswith(".snap"):
            cmd = "sudo snap install {} --classic --dangerous".format(upgrade_to)
        else:
            cmd = "sudo snap refresh microk8s --channel={}".format(upgrade_to)
        run_until_success(cmd)
        # Allow for the refresh to be processed
        time.sleep(10)
        wait_for_installation()

        # Test any validations that were valid for the original snap
        for test, validation in test_matrix.items():
            print("Testing {}".format(test))
            validation()

        if not is_container():
            # On lxc umount docker overlay is not permitted.
            check_call("sudo snap remove microk8s".split())
