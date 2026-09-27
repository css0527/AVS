#include <algorithm>
#include <atomic>
#include <cmath>
#include <gazebo/common/Events.hh>
#include <gazebo/common/Plugin.hh>
#include <gazebo/physics/physics.hh>
#include <gazebo_ros/node.hpp>
#include <std_msgs/msg/float64.hpp>

namespace avs_rescue {
// An ODE joint motor applies torque to the pan joint. Never change the model
// or link pose: doing so each scan tick disturbs wheel contacts and odometry.
class CameraPan : public gazebo::ModelPlugin {
 public:
  void Load(gazebo::physics::ModelPtr model, sdf::ElementPtr sdf) override {
    node_ = gazebo_ros::Node::Get(sdf);
    joint_ = model->GetJoint(sdf->Get<std::string>("joint_name", "camera_joint").first);
    gain_ = sdf->Get<double>("position_gain", 5.0).first;
    speed_ = sdf->Get<double>("max_velocity", 1.2).first;
    torque_ = sdf->Get<double>("max_torque", 0.1).first;
    if (!joint_) {RCLCPP_ERROR(node_->get_logger(), "Camera joint missing"); return;}
    subscription_ = node_->create_subscription<std_msgs::msg::Float64>(
      "/camera/pan_target", 1, [this](std_msgs::msg::Float64::ConstSharedPtr msg) {
        if (std::isfinite(msg->data)) target_.store(std::clamp(msg->data, -1.90, 1.90));
      });
    update_ = gazebo::event::Events::ConnectWorldUpdateBegin([this](const gazebo::common::UpdateInfo &) {
      joint_->SetParam("fmax", 0, torque_);
      joint_->SetParam("vel", 0, std::clamp(gain_ * (target_.load() - joint_->Position(0)), -speed_, speed_));
    });
  }
 private:
  gazebo_ros::Node::SharedPtr node_;
  gazebo::physics::JointPtr joint_;
  gazebo::event::ConnectionPtr update_;
  rclcpp::Subscription<std_msgs::msg::Float64>::SharedPtr subscription_;
  std::atomic<double> target_{0.0};
  double gain_, speed_, torque_;
};
GZ_REGISTER_MODEL_PLUGIN(CameraPan)
}
