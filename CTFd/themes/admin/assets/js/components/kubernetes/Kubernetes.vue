<template>
  <div>
    <div class="row mb-3">
      <div class="col-md-12">
        <div class="kubernetes-deployment-setting">
          <div>
            <input type="checkbox" id="kubernetesEnabledCheckbox" v-model="kubernetesEnabled" />
            <label for="kubernetesEnabledCheckbox">Enable Kubernetes Deployment?</label>
          </div>
          <codemirror
            v-model="kubeneretesDescriptionCode"
            v-if="kubernetesEnabled"
            :options="cmOptions" />
        </div>
      </div>
    </div>

    <button class="btn btn-success float-right" @click="submitDeployment()">
        Save Deployment
    </button>
  </div>
</template>

<script>
import CTFd from "core/CTFd";

import { codemirror } from 'vue-codemirror'
import 'codemirror/mode/yaml/yaml.js'
import 'codemirror/lib/codemirror.css'
import 'codemirror/theme/base16-dark.css'
// Needed because otherwise there is an empty window despite having set the text.
import "codemirror/addon/display/autorefresh.js";

import { ezToast } from 'core/ezq';

export default {
  props: {
    challenge_id: Number
  },
  components: {
    codemirror,
  },
  data: () => ({
    kubernetesEnabled: false,
    kubeneretesDescriptionCode: null,
    cmOptions: {
      tabSize: 2,
      mode: 'text/x-yaml',
      theme: 'base16-dark',
      lineNumbers: true,
      line: true,
      autofocus: true,
      autoRefresh: true,
    }
  }),
  methods: {
    loadKubernetesConfig: function() {
      CTFd.fetch(`/api/v1/challenges/${this.$props.challenge_id}`, {
        method: "GET",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json"
        }
      })
        .then(response => {
          return response.json();
        })
        .then(response => {
          if (response.success) {
            this.kubernetesEnabled = response.data.kubernetes_enabled ?? false,
            this.kubeneretesDescriptionCode = response.data.kubernetes_description ?? "";
          }
        });
    },
    submitDeployment: function() {
      const kubernetes_description = this.kubeneretesDescriptionCode.trim();
      const body = {
        kubernetes_enabled: this.kubernetesEnabled,
        kubernetes_description,
      };
      CTFd.fetch(`/api/v1/challenges/${this.challenge_id}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body),
      })
        .then((response) => response.json())
        .then((response) => {
          ezToast({
            title: "Sucessfully saved",
            body: `Your Kubernetes configuration is updated${body.kubernetes_enabled ? " and will be used on all new challenge starts": ""}.`
          })
        });

    },
  },
  created() {
    this.loadKubernetesConfig()
  }
};
</script>

<style scoped></style>
