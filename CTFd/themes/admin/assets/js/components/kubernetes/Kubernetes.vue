<template>
  <div>
    <div class="row mb-3">
      <div class="col-md-12">
        <div class="kubernetes-deployment-setting">
          <codemirror 
            v-model="kubeneretesDeploymentCode" 
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
import 'codemirror/mode/javascript/javascript.js'
import 'codemirror/mode/yaml/yaml.js'
import 'codemirror/lib/codemirror.css'
import 'codemirror/theme/base16-dark.css'
// Needed because otherwise there is an empty window despite having set the text.
import "codemirror/addon/display/autorefresh.js";

export default {
  props: {
    challenge_id: Number
  },
  components: {
    codemirror,
  },
  data: () => ({
    kubeneretesDeploymentCode: null,
    cmOptions: {
      tabSize: 2,
      mode: 'text/x-yaml',
      theme: 'base16-dark',
      lineNumbers: true,
      line: true,
      refresh: true,
      autofocus: false,
      autoRefresh: true,
    }
  }),
  methods: {
    loadDeploymentCode: function() {
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
            this.kubeneretesDeploymentCode = response.data.kubernetes_deployment ?? "";
          }
        });
    },
    submitDeployment: function() {
      let kubernetes_deployment = this.kubeneretesDeploymentCode.trim();
      if (kubernetes_deployment.length > 0) {
        const body = {
          kubernetes_deployment,
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
          .then(response => {
            console.log(response);
          });
      }
    },
  },
  mounted() {
    this.loadDeploymentCode()
  }
};
</script>

<style scoped></style>
